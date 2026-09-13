"""Discord-Bot: privater Voice-Channel als "Anruf" + DM-Pings.

Echte Telefonie (WhatsApp/Signal/Snapchat/Telegram) bietet keine Bot-APIs für
Sprachanrufe. Als kostenloser Ersatz tritt dieser Bot automatisch dem
konfigurierten Voice-Channel auf einem privaten Server bei, sobald der
Besitzer selbst reingeht — fühlt sich wie ein privater Anruf an, ohne
Telefonie-Kosten. Zusätzlich kann JARVIS über `notify()` eine DM schicken,
wenn eine Hintergrundaufgabe fertig ist (siehe panel.push("notify", ...)).

Läuft in einem eigenen Thread mit eigenem asyncio-Event-Loop, weil panel.py
(coder.py, tools.py, ...) aus synchronen Worker-Threads heraus aufgerufen
wird und den Bot per `asyncio.run_coroutine_threadsafe` ansprechen muss,
ohne mit dem FastAPI/uvicorn-Loop zu kollidieren. Ohne DISCORD_BOT_TOKEN
(oder ohne installiertes discord.py) ist alles hier ein No-Op.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading

from . import config

# discord.py loggt selbst auf dem Root-Logger — ohne eigenes Level bleibt es
# bei dessen Default (WARNING), sodass nur echte Verbindungsprobleme auftauchen.
logging.getLogger("discord").setLevel(logging.WARNING)

try:
    import discord
except ImportError:  # pragma: no cover - optionale Abhängigkeit
    discord = None

_client: "discord.Client | None" = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None


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


def _build_client() -> "discord.Client":
    intents = discord.Intents.default()
    intents.guilds = True
    intents.voice_states = True
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"[discord] verbunden als {client.user}")

    @client.event
    async def on_voice_state_update(member, before, after):
        # Besitzer betritt den konfigurierten Voice-Channel: Bot tritt bei
        # ("Anruf annehmen"). Besitzer verlässt ihn wieder und niemand sonst
        # ist mehr drin: Bot legt auf.
        owner_id = _owner_id()
        target_id = _voice_channel_id()
        if owner_id is None or target_id is None or member.id != owner_id:
            return
        if after.channel is not None and after.channel.id == target_id:
            existing = after.channel.guild.voice_client
            if existing is None:
                try:
                    await after.channel.connect()
                except Exception:
                    print("[discord] Voice-Join fehlgeschlagen")
            return
        if before.channel is not None and before.channel.id == target_id:
            vc = before.channel.guild.voice_client
            if vc is not None and not any(not m.bot for m in before.channel.members):
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
