"""Discord-Bot: privater Voice-Channel als "Anruf" + DM-Pings.

Echte Telefonie (WhatsApp/Signal/Snapchat/Telegram) bietet keine Bot-APIs für
Sprachanrufe. Als kostenloser Ersatz tritt dieser Bot automatisch dem
konfigurierten Voice-Channel auf einem privaten Server bei, sobald der
Besitzer selbst reingeht ("Anruf annehmen"), und kann über `notify()` eine
DM schicken, wenn eine Hintergrundaufgabe fertig ist (siehe
panel.push("notify", ...)).

Echtes Zuhören (Whisper-Transkription der eigenen Stimme -> LLM-Antwort ->
TTS zurück in den Channel) ist im Code vorhanden (_ConversationSink,
_process_utterance_sync, _listen_loop), aber DERZEIT NICHT ZUVERLÄSSIG
NUTZBAR: Discord verhandelt inzwischen auf praktisch jedem Voice-Channel
DAVE (Ende-zu-Ende-Verschlüsselung für Voice) hoch, sobald der Client sie
unterstützt (Paket `davey`, Pflicht-Abhängigkeit von discord.py[voice] seit
2.6+ — ohne sie verweigert discord.py auf DAVE-pflichtigen Servern die
Verbindung komplett). discord-ext-voice-recv (Alpha, 0.5.x) kennt das
DAVE-Framing aber nicht und versucht, die weiterhin verschlüsselten
Rohbytes direkt als Opus zu decodieren — das crasht mit
`discord.opus.OpusError: corrupted stream` und tötet den internen
Empfangs-Thread der Bibliothek endgültig (kein Absturz von JARVIS selbst,
aber ab dann kommt nie wieder Audio an, auch nicht nach Rejoin, bis der
ganze Bot-Prozess neu startet). Sprechen (TTS-Ausgabe über speak_wav_bytes)
und DM-Pings sind davon nicht betroffen — nur der Audio-Empfang.
Sollte discord-ext-voice-recv irgendwann DAVE unterstützen, braucht es hier
vermutlich keine Änderung, nur ein `pip install -U discord-ext-voice-recv`.

Läuft in einem eigenen Thread mit eigenem asyncio-Event-Loop, weil panel.py
(coder.py, tools.py, ...) aus synchronen Worker-Threads heraus aufgerufen
wird und den Bot per `asyncio.run_coroutine_threadsafe` ansprechen muss,
ohne mit dem FastAPI/uvicorn-Loop zu kollidieren. Ohne DISCORD_BOT_TOKEN
(oder ohne installiertes discord.py) ist alles hier ein No-Op.

stt/llm_client/tts werden absichtlich NICHT auf Modulebene importiert,
sondern erst innerhalb von _process_utterance_sync() — llm_client importiert
tools, tools importiert panel, und panel importiert dieses Modul hier; ein
Import auf Modulebene wäre also zirkulär (ImportError beim Start)."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
import wave

from . import config

# discord.py und discord.ext.voice_recv (dessen Module ausnahmslos
# getLogger(__name__) unter dem "discord"-Namespace benutzen) loggen selbst —
# WARNING statt DEBUG hält das im Normalbetrieb ruhig, zeigt aber echte
# Verbindungs-/Decrypt-Fehler (siehe Docstring oben) weiterhin an.
logging.getLogger("discord").setLevel(logging.WARNING)

try:
    import discord
except ImportError:  # pragma: no cover - optionale Abhängigkeit
    discord = None

try:
    import discord.ext.voice_recv as voice_recv
except ImportError:  # pragma: no cover - optionale Abhängigkeit
    voice_recv = None


def _ensure_opus_loaded() -> None:
    """discord.py braucht die native libopus zum Encodieren (Senden) und
    Decodieren (Empfangen) von Sprache — ohne sie kommt beim Senden nichts
    an und beim Empfangen wird write() nie mit echten Daten aufgerufen
    (kein Fehler, einfach Stille). discord.opus._load_default() findet sie
    über den System-Loader nicht immer, z. B. bei einer Homebrew-Installation
    auf macOS, deren lib-Pfad nicht im dyld-Suchpfad liegt — hier also
    explizit auf den üblichen Stellen nachsehen."""
    if discord is None or discord.opus.is_loaded():
        return
    try:
        discord.opus._load_default()
    except Exception:
        pass
    if discord.opus.is_loaded():
        return
    for candidate in (
        "/opt/homebrew/lib/libopus.0.dylib",  # macOS, Apple Silicon (Homebrew)
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.0.dylib",  # macOS, Intel (Homebrew)
        "/usr/local/lib/libopus.dylib",
        "libopus.so.0",  # Linux (apt/dnf)
        "libopus.so",
    ):
        try:
            discord.opus.load_opus(candidate)
            if discord.opus.is_loaded():
                print(f"[discord] libopus geladen: {candidate}")
                return
        except Exception:
            continue
    print("[discord] libopus nicht gefunden — Sprachaudio bleibt stumm (macOS: brew install opus)")

# Wie lange Stille nach der letzten empfangenen Sprachpaket-Zeit gilt, bevor
# der gesammelte Puffer als "fertig gesprochene" Äußerung verarbeitet wird.
SILENCE_SECONDS = 0.9
# Discord-Voice liefert PCM immer in diesem Format (siehe voice_recv.opus.Decoder).
_PCM_CHANNELS = 2
_PCM_SAMPLE_WIDTH = 2
_PCM_SAMPLE_RATE = 48000

_client: "discord.Client | None" = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_listen_task: "asyncio.Task | None" = None
_conversation_history: list = []
_join_lock = asyncio.Lock()


def _owner_id() -> int | None:
    try:
        return int(config.DISCORD_OWNER_USER_ID) if config.DISCORD_OWNER_USER_ID else None
    except ValueError:
        return None


def _voice_channel_id() -> int | None:
    try:
        return int(config.DISCORD_VOICE_CHANNEL_ID) if config.DISCORD_VOICE_CHANNEL_ID else None
    except ValueError:
        return None


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_PCM_CHANNELS)
        wf.setsampwidth(_PCM_SAMPLE_WIDTH)
        wf.setframerate(_PCM_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _process_utterance_sync(wav_bytes: bytes, vc) -> None:
    """Läuft in einem Thread-Pool-Worker (siehe _listen_loop) — blockierende
    Whisper-/LLM-/TTS-Aufrufe dürfen den Bot-Event-Loop nicht aufhalten."""
    from . import llm_client, stt, tts  # lazy — siehe Modul-Docstring

    try:
        text = (stt.transcribe(wav_bytes) or "").strip()
    except Exception:
        print("[discord] Transkription fehlgeschlagen")
        return
    if not text:
        return
    print(f"[discord] gehört: {text}")

    try:
        reply = llm_client.get_reply(text, _conversation_history, None)
    except Exception:
        print("[discord] LLM-Antwort fehlgeschlagen")
        return
    _conversation_history.append({"role": "user", "content": text})
    _conversation_history.append({"role": "assistant", "content": reply})
    del _conversation_history[:-40]
    print(f"[discord] Antwort: {reply}")

    try:
        wav_reply = tts.synthesize(reply)
    except Exception:
        print("[discord] TTS fehlgeschlagen")
        return
    if discord is not None and vc.is_connected():
        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(io.BytesIO(wav_reply), pipe=True))


class _ConversationSink(voice_recv.AudioSink if voice_recv else object):
    """Sammelt PCM-Audio des Besitzers, bis eine Sprechpause erkannt wird.
    write() läuft auf einem eigenen Empfangs-Thread von discord-ext-voice-recv
    (nicht dem asyncio-Loop) — daher der Lock statt asyncio-Primitiven."""

    def __init__(self, owner_id: int):
        super().__init__()
        self._owner_id = owner_id
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._last_write = 0.0

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:  # noqa: D401 - Basisklassen-Signatur
        if user is None or user.id != self._owner_id:
            return
        vc = self.voice_client
        if vc is not None and vc.is_playing():
            return  # Jarvis spricht gerade — kein Barge-in in dieser Version.
        with self._lock:
            self._buffer.extend(data.pcm)
            self._last_write = time.monotonic()

    def cleanup(self) -> None:
        pass

    def pop_if_silent(self, silence_s: float) -> bytes | None:
        with self._lock:
            if not self._buffer or time.monotonic() - self._last_write < silence_s:
                return None
            chunk = bytes(self._buffer)
            self._buffer.clear()
            return chunk


async def _listen_loop(sink: "_ConversationSink", vc) -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            await asyncio.sleep(0.25)
            pcm = sink.pop_if_silent(SILENCE_SECONDS)
            if pcm:
                await loop.run_in_executor(None, _process_utterance_sync, _pcm_to_wav(pcm), vc)
    except asyncio.CancelledError:
        pass


async def _join_and_listen(channel, owner_id: int) -> None:
    """Tritt `channel` bei und startet die Sprach-Loop. No-Op, falls der Bot
    (laut discord.py-Client-Status) schon in einem Channel dieser Guild ist —
    ein neuer Prozess weiß davon nichts, `guild.voice_client` ist dann immer
    frisch None, auch wenn Discord noch eine tote Geister-Session anzeigt."""
    global _listen_task
    async with _join_lock:
        if channel.guild.voice_client is not None:
            return
        await _do_join_and_listen(channel, owner_id)


async def _do_join_and_listen(channel, owner_id: int) -> None:
    global _listen_task
    try:
        if voice_recv is not None:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
            _conversation_history.clear()
            sink = _ConversationSink(owner_id)
            vc.listen(sink)
            _listen_task = asyncio.get_running_loop().create_task(_listen_loop(sink, vc))
            print(f"[discord] verbunden + höre zu (owner={owner_id}, opus_loaded={discord.opus.is_loaded()})")
        else:
            await channel.connect()
            print("[discord] discord-ext-voice-recv fehlt — Bot ist stumm dabei, hört aber nicht zu")
    except Exception as exc:
        print(f"[discord] Voice-Join fehlgeschlagen: {exc!r}")


def _build_client() -> "discord.Client":
    intents = discord.Intents.default()
    intents.guilds = True
    intents.voice_states = True
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"[discord] verbunden als {client.user}")
        # Besitzer war schon vor diesem (Neu-)Start im Channel — ohne das hier
        # würde nie ein voice_state_update-Event feuern (es ändert sich ja
        # nichts an seinem Status) und der Bot bliebe für immer draußen.
        owner_id = _owner_id()
        target_id = _voice_channel_id()
        if owner_id is None or target_id is None:
            return
        channel = client.get_channel(target_id)
        if channel is not None and any(m.id == owner_id for m in channel.members):
            await _join_and_listen(channel, owner_id)

    @client.event
    async def on_voice_state_update(member, before, after):
        # Besitzer betritt den konfigurierten Voice-Channel: Bot tritt bei
        # ("Anruf annehmen"), hört ab jetzt mit. Besitzer verlässt ihn wieder
        # und niemand sonst ist mehr drin: Bot legt auf.
        global _listen_task
        owner_id = _owner_id()
        target_id = _voice_channel_id()
        if owner_id is None or target_id is None or member.id != owner_id:
            return
        if after.channel is not None and after.channel.id == target_id:
            await _join_and_listen(after.channel, owner_id)
            return
        if before.channel is not None and before.channel.id == target_id:
            vc = before.channel.guild.voice_client
            if vc is not None and not any(not m.bot for m in before.channel.members):
                if _listen_task is not None:
                    _listen_task.cancel()
                    _listen_task = None
                await vc.disconnect()

    return client


def start() -> None:
    """Startet den Discord-Bot im Hintergrund. No-Op ohne Token/Bibliothek."""
    global _thread
    if not config.DISCORD_BOT_TOKEN:
        return
    if discord is None:
        print("[discord] discord.py nicht installiert — Integration deaktiviert (pip install -r requirements.txt)")
        return
    if _thread is not None:
        return
    _ensure_opus_loaded()

    def runner():
        global _loop, _client
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _loop = loop
        client = _build_client()
        _client = client
        try:
            loop.run_until_complete(client.start(config.DISCORD_BOT_TOKEN))
        except Exception:
            print("[discord] Bot-Thread beendet mit Fehler")

    _thread = threading.Thread(target=runner, daemon=True, name="jarvis-discord")
    _thread.start()


def _run_coro(coro) -> None:
    if _loop is None:
        coro.close()
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, _loop)
    except Exception:
        print("[discord] Aktion konnte nicht eingeplant werden")


def notify(text: str) -> None:
    """Schickt eine DM an DISCORD_OWNER_USER_ID. Best-effort, blockiert nicht
    — wird von panel.push("notify", ...) aus jedem Worker-Thread aufgerufen."""
    owner_id = _owner_id()
    if owner_id is None or _client is None:
        return

    async def _send():
        try:
            user = await _client.fetch_user(owner_id)
            await user.send(text)
        except Exception:
            print("[discord] DM fehlgeschlagen")

    _run_coro(_send())


def speak_wav_bytes(wav_bytes: bytes) -> None:
    """Spielt WAV-Audio (z. B. von backend/tts.py) im aktuell verbundenen
    Voice-Channel ab, falls der Bot gerade in einem sitzt. Braucht ffmpeg
    auf dem PATH (piped die WAV-Bytes durch FFmpegPCMAudio)."""
    if _client is None or discord is None:
        return

    async def _play():
        for vc in list(_client.voice_clients):
            if vc.is_playing():
                vc.stop()
            source = discord.FFmpegPCMAudio(io.BytesIO(wav_bytes), pipe=True)
            vc.play(source)

    _run_coro(_play())
