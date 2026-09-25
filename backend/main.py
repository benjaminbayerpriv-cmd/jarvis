from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, File, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import browser_agent, config, conversations, fillers, hardware, llm_client, memory, opencode_agent, panel, projects, stt, transcript_log, tts, vector_memory

# Jarvis exposes run_shell, file writes and a live coding-agent terminal over
# plain local HTTP/WebSocket. With CORS open to "*" and no origin check on the
# websockets, any web page open in the user's browser could drive all of that
# in the background (fetch to /chat/stream, keystrokes into /code/tty/ws).
# Only the app itself (same origin) and the Chrome extension may talk to it;
# requests without an Origin header come from non-browser clients (hotkey
# listener, scripts) and stay allowed.
_EXTENSION_ORIGIN_RE = re.compile(r"^chrome-extension://[a-p]{32}$")


def _host_is_trusted(host: str) -> bool:
    # The app is only ever addressed by IP or "localhost" — a domain name in
    # Host means a DNS-rebinding page (attacker domain resolving to 127.0.0.1).
    hostname = (urlparse(f"//{host}").hostname or "").lower()
    if hostname == "localhost":
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _request_allowed(origin: str | None, host: str | None) -> bool:
    if host and not _host_is_trusted(host):
        return False
    if not origin:
        return True
    if _EXTENSION_ORIGIN_RE.match(origin):
        return True
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and bool(host) and parsed.netloc == host


class _OriginGuard:
    """Plain ASGI middleware (not BaseHTTPMiddleware) so it covers websockets
    too and never buffers the streaming chat responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if not _request_allowed(headers.get("origin"), headers.get("host")):
                print(f"[security] Anfrage abgelehnt: origin={headers.get('origin')!r} host={headers.get('host')!r} {scope.get('path')}")
                if scope["type"] == "http":
                    await JSONResponse({"detail": "Anfrage von fremder Herkunft abgelehnt."}, status_code=403)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


app = FastAPI(title="Jarvis")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_EXTENSION_ORIGIN_RE.pattern,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(_OriginGuard)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
# Frozen copy of the UI from before a redesign (see /backup below) — kept as
# a real, always-available fallback rather than a local-only, gitignored
# folder, so it survives a fresh clone/deploy too.
FRONTEND_BACKUP_DIR = Path(__file__).resolve().parent.parent / "frontend_backup"

active_sockets: list[WebSocket] = []
filler_urls: list[str] = []
thinking_filler_url: str | None = None


# Emoji-Range, die aus KI-Antworten entfernt werden. Der Nutzer will keine
# Emojis in den Antworten — weder im Text noch in der Sprachausgabe. Der Filter
# sitzt an EINER Stelle (hier), damit Display UND TTS denselben bereinigten
# Text erhalten. Entfernt werden die farbigen Piktogramm-Blöcke (U+1F000–U+1FAFF),
# die klassischen BMP-Symbole (U+2600–U+27BF, U+2B00–U+2BFF, U+2300–U+23FF für
# Emoji-Defaults wie ⏰⌚), regionale Flags (U+1F1E6–U+1F1FF), Skin-Tones
# (U+1F3FB–U+1F3FF), das Joiner-Zeichen (U+200D, zerlegt ZWJ-Komposita wie
# 👨‍👩‍👧 in Einzelzeichen) und die Variationsselektoren (U+FE00–U+FE0F).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # Piktogramme: Smileys, 💡, 🚀, Tiere, …
    "\U0001F1E6-\U0001F1FF"  # regionale Indikatoren (Flaggen)
    "\U00002300-\U000023FF"  # ⌚⏰⌛⏳ (emoji-default)
    "\U00002600-\U000027BF"  # ⭐❌✅⚠❤✨ …
    "\U00002B00-\U00002BFF"  # wiederkehrende Symbolpfeile/Formen
    "\U0001F3FB-\U0001F3FF"  # Hauttöne
    "\U0000200D"  # ZWJ (Zero-Width-Joiner)
    "\U000020E3"  # Keycap-Combiner
    "\U0000FE00-\U0000FE0F"  # Variationsselektoren
    "]"
)


def _strip_emojis(text: str) -> str:
    """Entfernt Emojis aus einer Antwort; lässt normalen Text unangetastet."""
    if not text:
        return text
    return _EMOJI_RE.sub("", text)


async def broadcast(payload: dict) -> None:
    dead = []
    for ws in active_sockets:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in active_sockets:
            active_sockets.remove(ws)


async def _pump_panel():
    """Forward queued panel items to every open interface.

    Panel content travels over the websocket rather than the chat response
    so that work finishing long after its turn ended — a background
    build_project, for instance — can still show up and announce itself.
    """
    while True:
        for item in panel.drain():
            await broadcast({"type": "panel", "item": item})
        await asyncio.sleep(0.2)


@app.on_event("startup")
async def on_startup():
    """Warm the filler clips (ElevenLabs is only hit for ones not already
    cached on disk) and start the panel pump."""
    global filler_urls, thinking_filler_url
    memory.initialize()
    fit = hardware.check_model(config.LM_STUDIO_MODEL)
    if not fit["fits"]:
        hardware.block(config.LM_STUDIO_MODEL, fit["message"])
        print(f"[model] {fit['message']}")
        panel.push("notify", text=fit["message"])
    healthy, detail = llm_client.model_health()
    # model_health only checks that LM Studio lists the model, so its
    # "Modell bereit" would contradict the too-large warning just given.
    if fit["fits"]:
        print(f"[model] {detail}")
        if not healthy:
            panel.push("notify", text=detail)

    def _generate():
        global filler_urls, thinking_filler_url
        filler_urls = fillers.ensure_fillers()
        thinking_filler_url = fillers.ensure_thinking_filler()

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _generate)
    # Whisper's first load takes ~15s — do it now instead of on the user's
    # first spoken sentence. selftest() (not just _get_model()) also runs a
    # real transcription so a broken GPU setup (e.g. a missing cuBLAS DLL)
    # surfaces here, in the log, rather than on the user's first sentence —
    # model construction alone never touches cuBLAS/cuDNN.
    loop.run_in_executor(None, stt.selftest)
    # Backfills the semantic-search index for any vault content written
    # before this feature existed (or added directly in Obsidian, outside
    # Jarvis) — see backend/vector_memory.py. Already-indexed lines are
    # skipped, so this is cheap on every startup after the first.
    loop.run_in_executor(None, vector_memory.reindex_all)
    loop.create_task(_pump_panel())


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    turn_id: str | None = None
    conversation_id: str | None = None
    mode: str = "chat"  # "chat" | "code" — Chat|Code-Umschalter im Frontend
    # Data-URLs ("data:image/jpeg;base64,...") vom Datei-Anhang im Frontend —
    # nur an vision-fähige Modelle weitergereicht, siehe llm_client._build_messages.
    images: list[str] | None = None
    # Nur relevant, wenn diese Nachricht die Konversation neu anlegt (siehe
    # conversations.append_turn) — verknüpft sie dauerhaft mit dem Projekt,
    # aus dessen Detailansicht heraus gesendet wurde.
    project_id: str | None = None
    # Ob dieser Turn aus dem Sprachmodus kommt (siehe llm_client._system_prompt) —
    # nur dann gilt "wird vorgelesen, fasse dich kurz". Ohne dieses Feld nahm
    # der System-Prompt das für JEDEN Turn an, auch getippten Text im
    # normalen Chat, und Jarvis antwortete dort unnötig einsilbig.
    is_speech: bool = False


class CancelRequest(BaseModel):
    turn_id: str


class SelectModelRequest(BaseModel):
    model: str
    # "Trotzdem laden" im Modell-Auswahlmenü — überspringt hardware.py's
    # Speicher-Check, statt den Nutzer auf Chat-Nachrichten zu verweisen, wo
    # dieselbe Umgehung schon existiert (siehe /model/force-load).
    force: bool = False


class UpdateSettingsRequest(BaseModel):
    lm_studio_base_url: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    supertonic_voice: str | None = None
    supertonic_lang: str | None = None
    whisper_model: str | None = None
    embedding_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None
    # Hart aus/an, unabhängig von den Feldern oben — siehe
    # config.DEEPSEEK_ENABLED/set_deepseek_enabled. Bool statt der
    # generischen _SIMPLE_SETTINGS-Strings, weil es eine echte
    # Typkonvertierung braucht.
    deepseek_enabled: bool | None = None
    tavily_api_key: str | None = None


class CreateProjectRequest(BaseModel):
    dir: str
    name: str = ""
    description: str = ""
    tag: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    pinned: bool | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class RenameCodeSessionRequest(BaseModel):
    title: str


class ChatResponse(BaseModel):
    reply: str


class SummarizeRequest(BaseModel):
    history: list[dict]


class SummarizeResponse(BaseModel):
    summary: str


class BrowserResult(BaseModel):
    id: str
    ok: bool
    message: str = ""
    error: str = ""
    data: dict = {}


# The interface is edited constantly and served from disk; browser caching
# just means staring at a stale page after every change.
_NO_CACHE = {"Cache-Control": "no-store, must-revalidate"}

# no-store alone doesn't help for assets a browser cached *before* the header
# existed, so asset URLs also carry a build stamp that changes on restart.
_BUILD = str(int(time.time()))


def _freeze_snapshot(html: str) -> str:
    """Freeze the claude.ai SSR DOM so React never re-hydrates.

    website.html is a server-rendered (SSR) snapshot of the *logged-in*
    Anthropic client. If the client bundles are allowed to boot they
    immediately re-run the auth gate, find no session, and the router
    redirects to /login — which this offline server has no route for, so the
    user just sees a bare 404 JSON instead of the UI. Stripping every <script>
    keeps the full SSR markup (sidebar, conversation list, composer) as static
    HTML+CSS: the exact claude.ai look, fully offline, no redirect.
    """
    html = re.sub(r"<script\b[^>]*>(?:(?!</script>).)*?</script>\s*", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script\b[^>]*/>", "", html, flags=re.IGNORECASE)
    return html


def _render_app_shell(frontend_dir: Path, static_prefix: str) -> str:
    """Build the claude.html-based app shell from the given frontend
    directory, with the functional JS layer injected against the given
    /static-style URL prefix. Shared by / (the live, constantly-redesigned
    UI) and /backup (the frozen pre-redesign fallback, see FRONTEND_BACKUP_DIR)
    so both stay byte-for-byte the same wiring, just pointed at different
    asset trees.
    #
    # Explicit encoding matters here: Path.read_text() defaults to the OS
    # locale's preferred encoding, which is cp1252 on German Windows, not
    # UTF-8 — the file itself is UTF-8, so without this every special
    # character in it (observed live: the "≡" debug-toggle symbol) gets
    # silently mangled into mojibake before it's ever served to the browser.
    """
    html = (frontend_dir / "claude.html").read_text(encoding="utf-8")
    html = _freeze_snapshot(html)
    # The frozen snapshot must not let the Anthropic client boot (it would
    # bounce to a /login 404). It also must not be completely static: inject
    # our own functional layer, which drives the same 1:1 claude.ai DOM.
    # Einen Build-Stempel an die Skript-URL hängen: claude-app.js wird ständig
    # umgebaut, und no-store allein hilft nicht gegen ein bereits zuvor
    # gecachtes Skript — ohne ?v= bleibt ein alter Browser hartnäckig bei der
    # alten, kollabierten Version hängen und der User sähe weiter die tote UI.
    # Der Code-Tab rendert die echte opencode-TUI in einem xterm.js-Terminal,
    # also lokal die xterm-Bundles (als static/*) direkt vor claude-app.js laden.
    assets = (
        '    <link rel="stylesheet" href="{p}/xterm.css?v={v}\">\n'.format(p=static_prefix, v=_BUILD)
        + '    <script src="{p}/xterm.js?v={v}"></script>\n'.format(p=static_prefix, v=_BUILD)
        + '    <script src="{p}/xterm-addon-fit.js?v={v}"></script>\n'.format(p=static_prefix, v=_BUILD)
        + '    <script src="{p}/claude-app.js?v={v}"></script>\n'.format(p=static_prefix, v=_BUILD)
    )
    return html.replace("</body>", f"{assets}  </body>")


@app.get("/")
def serve_index():
    # The start page is JARVIS's own functional UI layer (see claude-app.js's
    # buildUi()), rendered over the frozen claude.html SSR snapshot (its
    # Anthropic scripts stripped, see _freeze_snapshot — the snapshot itself
    # is invisible, it only still supplies a couple of CSS font fallbacks).
    # The previous JARVIS UI still lives at frontend/index.html (with its own
    # style.css/app.js) and remains reachable via the /static/* mount for
    # reference, but is no longer served on /. See /backup for a frozen
    # snapshot of the UI from before the most recent redesign.
    return HTMLResponse(_render_app_shell(FRONTEND_DIR, "/static"), headers=_NO_CACHE)


@app.get("/backup")
def serve_backup_ui():
    """A frozen copy of the UI as it was before the most recent redesign,
    always reachable at /backup regardless of what / currently looks like —
    kept as a real fallback (and an easy before/after comparison) rather
    than a local-only copy that only exists on whoever's machine happened to
    make it. Talks to the exact same live backend as / (same /chat/stream,
    /code/*, /settings, … endpoints), just with the older HTML/JS shell."""
    if not (FRONTEND_BACKUP_DIR / "claude.html").exists():
        raise HTTPException(status_code=404, detail="Kein UI-Backup vorhanden (frontend_backup/ fehlt).")
    return HTMLResponse(_render_app_shell(FRONTEND_BACKUP_DIR, "/backup-static"), headers=_NO_CACHE)


_JARVIS_FAVICON_PATH = FRONTEND_DIR / "assets" / "img" / "favicon.ico"


@app.get("/favicon.ico")
def favicon():
    """Own JARVIS icon (the terracotta logo) at the browser's default probe
    path, so the frozen claude.ai snapshot never leaks Anthropic's own logo
    into the tab bar (the SSR markup links its shortcut icon to /favicon.ico,
    and Chrome probes it regardless of the rel="icon" link it also carries)."""
    return Response(_JARVIS_FAVICON_PATH.read_bytes(), media_type="image/x-icon")


class NoCacheStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(_NO_CACHE)
        return resp


app.mount("/static", NoCacheStatic(directory=FRONTEND_DIR), name="static")
if FRONTEND_BACKUP_DIR.exists():
    app.mount("/backup-static", NoCacheStatic(directory=FRONTEND_BACKUP_DIR), name="backup-static")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        reply = llm_client.get_reply(req.message, req.history, req.mode)
    except llm_client.ModelTooLargeError as exc:
        reply = str(exc)
    except (requests.RequestException, llm_client.ModelError):
        reply = (
            "I can't reach my language model right now. "
            "Is LM Studio running and has its server been started?"
        )
    return ChatResponse(reply=reply)


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    """Condense old chat turns the frontend is about to drop from its
    rolling history window, instead of just discarding them outright."""
    try:
        loop = asyncio.get_running_loop()
        summary = await loop.run_in_executor(None, llm_client.summarize_history, req.history)
    except (requests.RequestException, llm_client.ModelError):
        summary = ""
    return SummarizeResponse(summary=summary)


@app.post("/tts")
def speak(req: ChatResponse):
    try:
        audio = tts.synthesize(req.reply)
    except Exception:
        return Response(status_code=502, content=b"")
    _, mime = tts.ENGINE_MEDIA.get(tts.VoiceInfo.engine, ("mp3", "audio/mpeg"))
    return Response(content=audio, media_type=mime)


class TtsStreamRequest(BaseModel):
    text: str
    mode: str = "sentence"  # "sentence" | "clause"
    seed: int | None = None
    steps: int = 8


@app.post("/tts/stream")
def speak_stream(req: TtsStreamRequest):
    """Testweg ohne LLM: synthetisiert den übergebenen Text mit Supertonic
    Häppchen für Häppchen und schickt jedes fertige WAV sofort als NDJSON-
    Zeile raus, damit die Testseite es abspielen kann, während der Rest noch
    berechnet wird."""
    def generate():
        start = time.time()
        try:
            for i, (wav, chunk) in enumerate(tts.synthesize_stream(req.text, req.mode, req.seed, req.steps)):
                yield json.dumps({
                    "type": "audio",
                    "index": i,
                    "text": chunk,
                    "audio": base64.b64encode(wav).decode("ascii"),
                    "mime": "audio/wav",
                    "elapsed_ms": int((time.time() - start) * 1000),
                }) + "\n"
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
        yield json.dumps({"type": "done", "elapsed_ms": int((time.time() - start) * 1000)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/stt")
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    try:
        # stt.transcribe() is a blocking, CPU-bound Whisper call (real
        # seconds, not milliseconds) — run directly inside this async def it
        # would freeze the whole event loop for that whole time, so no other
        # request (a second /stt call from the very next utterance, the
        # websocket panel pump, a /tts or /chat/stream request) could be
        # served until it finished. Offloading it to a worker thread is what
        # actually lets a real utterance get processed promptly even if an
        # earlier one (e.g. a VAD false-trigger during a long silence) is
        # still being transcribed.
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, stt.transcribe, data)
    except Exception as exc:
        print(f"[stt] Transkription fehlgeschlagen: {exc}")
        return {"text": ""}
    return {"text": text}


def _project_chats_dir(project_id: str | None):
    """Resolves a project id to its chats folder (inside the project's own
    directory on disk — see projects.chats_dir), or None for the default
    central conversations store. Returns None (not an error) for an unknown
    project id, e.g. a stale project_id from before it was deleted; the
    caller falls back to the default store rather than losing the turn."""
    if not project_id:
        return None
    project = projects.get(project_id)
    return projects.chats_dir(project) if project else None


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Streams the reply as newline-delimited JSON, one line per sentence,
    each carrying that sentence's already-synthesized audio — so playback
    can start after the first sentence instead of waiting for the whole
    reply plus a single big TTS call."""

    conv_id = req.conversation_id or conversations.new_id()
    # Resolved once per request from req.project_id — every turn of a
    # project-backed conversation re-resolves the same folder this way
    # (never trusts a client-cached path), so it stays correct even if the
    # project's record changes between turns.
    chats_base_dir = _project_chats_dir(req.project_id)

    def _generate_title_in_background(user_text: str, assistant_text: str) -> None:
        # Fire-and-forget: an extra LLM round-trip for the title must never
        # hold the HTTP response (and with it, the frontend's turn) open —
        # the sidebar just shows the generic label until this lands and the
        # next conversation-list refresh picks it up.
        def _job():
            try:
                title = llm_client.generate_title(user_text, assistant_text)
            except (requests.RequestException, llm_client.ModelError):
                title = ""
            if title:
                conversations.set_title(conv_id, title, chats_base_dir)

        threading.Thread(target=_job, daemon=True).start()

    def generate():
        full_text = ""
        try:
            for event in llm_client.stream_reply(req.message, req.history, turn_id=req.turn_id, mode=req.mode, images=req.images, is_speech=req.is_speech):
                if event["type"] == "sentence":
                    text = _strip_emojis(event["text"])
                    # Leere Sätze (löst ein Reasoning-Modell manchmal am Ende aus)
                    # ganz überspringen — weder anzeigen noch (den Mini-Botch)
                    # vertonen.
                    if not text.strip():
                        continue
                    # Text wird SOFORT geschickt — TTS-Synthese dauert real
                    # Sekunden, und der Nutzer soll nicht auf die Stimme warten,
                    # nur um überhaupt etwas zu sehen. Die Worte gehen zuerst
                    # raus (leeres audio), der Klang folgt als eigener
                    # "audio"-Event, sobald er fertig ist. Schlägt die
                    # Synthese fehl, ist trotzdem der Text da (nie den Satz
                    # verschlucken, nur den Ton).
                    yield json.dumps({"type": "sentence", "text": text, "audio": ""}) + "\n"
                    # Outside speech mode the frontend throws audio away — and
                    # synthesizing it here holds up the next sentence by the
                    # full TTS time, so typed chats got slower for nothing.
                    if not req.is_speech:
                        continue
                    try:
                        # Ein langer Satz wird an seiner ersten Kommapause in
                        # zwei Sprech-Häppchen geteilt (siehe tts.split_for_
                        # speech) — jedes geht als eigenes "audio"-Event raus,
                        # die Frontend-Queue spielt sie einfach nacheinander
                        # ab. So beginnt die Wiedergabe schon beim ersten
                        # Teilsatz, während der Rest noch synthetisiert wird,
                        # statt auf den ganzen Satz warten zu müssen.
                        for chunk in tts.split_for_speech(text):
                            audio = tts.synthesize(chunk)
                            audio_b64 = base64.b64encode(audio).decode("ascii")
                            _, mime = tts.ENGINE_MEDIA.get(tts.VoiceInfo.engine, ("mp3", "audio/mpeg"))
                            yield json.dumps({"type": "audio", "audio": audio_b64, "mime": mime}) + "\n"
                    except Exception as exc:  # noqa: BLE001 - nie nur-wortlos
                        print(f"[tts] Sprachausgabe fehlgeschlagen: {exc}")
                elif event["type"] == "partial":
                    # Zwischentext des noch unfertigen Satzes — sofort weiter,
                    # damit der Nutzer live mitlesen kann. Kein Audio, nur Text.
                    yield json.dumps({"type": "partial", "text": _strip_emojis(event["text"])}) + "\n"
                elif event["type"] == "done":
                    full_text = _strip_emojis(event["full_text"])
                    yield json.dumps(
                        {"type": "done", "full_text": full_text, "conversation_id": conv_id}
                    ) + "\n"
            if full_text:
                transcript_log.log_turn(req.message, full_text, req.mode)
                conv = conversations.append_turn(conv_id, req.message, full_text, req.project_id, chats_base_dir)
                if conv.get("title") is None and len(conv.get("turns", [])) == 2:
                    _generate_title_in_background(req.message, full_text)
        except (requests.RequestException, llm_client.ModelError, KeyError, IndexError) as exc:
            fallback = (
                str(exc) if isinstance(exc, llm_client.ModelTooLargeError) else
                "I can't reach my language model right now. "
                "Please check whether Gemma is loaded in LM Studio."
            )
            print(f"[model] Anfrage fehlgeschlagen: {exc}")
            if isinstance(exc, llm_client.ModelTooLargeError):
                # Structured event alongside the plain text, so the frontend
                # can attach real "Trotzdem laden" / "Modell entladen"
                # buttons instead of the user being stuck with an inert
                # message every single turn until they dig into Settings.
                yield json.dumps({"type": "hardware_block", "model": config.LM_STUDIO_MODEL}) + "\n"
            audio_b64 = ""
            if req.is_speech:
                try:
                    audio_b64 = base64.b64encode(tts.synthesize(fallback)).decode("ascii")
                except Exception as tts_exc:  # noqa: BLE001 - the text must still arrive
                    print(f"[tts] Sprachausgabe fehlgeschlagen: {tts_exc}")
            yield json.dumps({"type": "sentence", "text": fallback, "audio": audio_b64}) + "\n"
            yield json.dumps({"type": "done", "full_text": fallback, "conversation_id": conv_id}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/chat/cancel")
def chat_cancel(req: CancelRequest):
    """Called by the frontend's stop button. A tool call (open_url and
    friends) runs synchronously inside stream_reply with no yield point in
    between — the HTTP connection dropping when the browser aborts its
    fetch is invisible to that running generator, so without this a click
    on Stop could never actually stop an action already underway, only
    silence the reply once it came back. This flags the turn so
    stream_reply can check it right before the next tool actually runs."""
    llm_client.cancel_turn(req.turn_id)
    return {"ok": True}


@app.post("/shutdown")
def shutdown():
    """Called by quitBtn — ends the whole running program, not just this
    browser tab. os._exit() (not sys.exit, which only raises inside the
    calling thread and would just kill this one request handler) runs on a
    short delay from a separate thread so the response below actually
    reaches the browser before the process disappears out from under it."""

    def _die():
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
    return {"ok": True}


@app.get("/transcript")
def transcript():
    """Scroll-back for the chat panel on open — backend/transcript.log is
    already written on every turn regardless of whether this panel is ever
    opened, so this just reads it back instead of the panel only ever
    showing turns from the current page session."""
    return {"turns": transcript_log.read_recent_turns()}


@app.get("/conversations")
def get_conversations(project_id: str | None = None):
    """Metadata for the sidebar's conversation list — newest first, each
    with its auto-generated title (see llm_client.generate_title). Pass
    project_id to list that project's conversations instead (from its own
    folder on disk — see projects.chats_dir) for the project detail page's
    "Zuletzt verwendet" list. Unlike chat_stream's use of
    _project_chats_dir, an unresolvable project here must NOT fall back to
    the global store — that would leak every unrelated conversation into
    this project's page instead of showing it has none."""
    if project_id:
        base_dir = _project_chats_dir(project_id)
        return {"conversations": conversations.list_conversations(base_dir) if base_dir else []}
    return {"conversations": conversations.list_conversations()}


@app.get("/conversations/{conv_id}")
def get_conversation(conv_id: str, project_id: str | None = None):
    """Full turn list for one conversation, fetched when a sidebar or
    project "Zuletzt verwendet" entry is clicked. project_id must be passed
    for a project-backed conversation — that's the only way this endpoint
    knows which folder on disk to look in. See get_conversations for why an
    unresolvable project_id returns empty rather than falling back."""
    if project_id:
        base_dir = _project_chats_dir(project_id)
        return {"turns": conversations.load_turns(conv_id, base_dir) if base_dir else []}
    return {"turns": conversations.load_turns(conv_id)}


@app.patch("/conversations/{conv_id}")
def update_conversation(conv_id: str, req: UpdateConversationRequest, project_id: str | None = None):
    """Rename and/or pin a conversation from the sidebar's three-dot menu."""
    base_dir = _project_chats_dir(project_id) if project_id else None
    if req.title is not None:
        if not req.title.strip():
            raise HTTPException(status_code=422, detail="Titel darf nicht leer sein")
        conversations.set_title(conv_id, req.title.strip(), base_dir)
    if req.pinned is not None:
        conversations.set_pinned(conv_id, req.pinned, base_dir)
    return {"ok": True}


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, project_id: str | None = None):
    base_dir = _project_chats_dir(project_id) if project_id else None
    conversations.delete(conv_id, base_dir)
    return {"ok": True}


@app.post("/conversations/{conv_id}/reveal")
def reveal_conversation(conv_id: str, project_id: str | None = None):
    """Opens the OS file manager with the conversation's JSON file
    selected — the "im Ordner anzeigen" entry in the sidebar's three-dot
    menu, a stand-in for a full "open with <app>" until that's scoped out
    (Windows-only for now; the rest of Jarvis already assumes Windows)."""
    base_dir = _project_chats_dir(project_id) if project_id else None
    path = conversations.file_path(conv_id, base_dir)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")
    if sys.platform != "win32":
        raise HTTPException(status_code=501, detail="Nur unter Windows unterstützt")
    subprocess.run(["explorer", "/select,", str(path)])
    return {"ok": True}


@app.get("/projects")
def get_projects():
    return {"projects": projects.list_projects()}


@app.post("/projects")
def create_project(req: CreateProjectRequest):
    if not req.dir.strip():
        raise HTTPException(status_code=422, detail="Ordner darf nicht leer sein")
    try:
        return projects.create(req.dir, req.name, req.description, req.tag)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Ordner konnte nicht angelegt/geöffnet werden: {exc}")


@app.patch("/projects/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest):
    if req.name is not None and not req.name.strip():
        raise HTTPException(status_code=422, detail="name darf nicht leer sein")
    updated = projects.update(project_id, req.name, req.description, req.pinned)
    if updated is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return updated


@app.delete("/projects/{project_id}")
def delete_project(project_id: str):
    projects.delete(project_id)
    return {"ok": True}


@app.get("/settings")
def get_settings():
    return {
        "lm_studio_base_url": config.LM_STUDIO_BASE_URL,
        "deepseek_enabled": config.DEEPSEEK_ENABLED,
        **config.get_simple_settings(),
    }


@app.get("/model/health")
def model_health():
    """Whether any chat model is actually reachable right now (LM Studio or
    the configured DeepSeek fallback) — checked live, not just once at
    startup, so the frontend can grey out the composer whenever LM Studio
    gets stopped or the endpoint/API key is wrong, and re-enable it the
    moment the user fixes it in Settings without needing a page reload."""
    healthy, detail = llm_client.model_health()
    return {"healthy": healthy, "detail": detail}


@app.post("/model/test")
def model_test(req: UpdateSettingsRequest):
    """Test-drives a CANDIDATE LM Studio endpoint or DeepSeek API key without
    persisting it — backs the inline setup panel the composer shows when no
    model is reachable ("Testen" button): the user can try a value before
    committing to it via POST /settings ("Freischalten" in the frontend)."""
    if req.deepseek_api_key and req.deepseek_api_key.strip():
        base = (req.deepseek_base_url or config.DEEPSEEK_BASE_URL).rstrip("/")
        try:
            resp = requests.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {req.deepseek_api_key.strip()}"},
                timeout=6,
            )
            resp.raise_for_status()
            return {"healthy": True, "detail": "DeepSeek erreichbar."}
        except requests.RequestException as exc:
            return {"healthy": False, "detail": f"DeepSeek nicht erreichbar: {exc}"}

    base = (req.lm_studio_base_url or config.LM_STUDIO_BASE_URL or "").strip().rstrip("/")
    if not base:
        return {"healthy": False, "detail": "Bitte einen Endpoint oder API-Key eintragen."}
    try:
        resp = requests.get(f"{base}/models", timeout=6)
        resp.raise_for_status()
        models = [entry.get("id") for entry in resp.json().get("data", []) if entry.get("id")]
    except requests.RequestException as exc:
        return {"healthy": False, "detail": f"Nicht erreichbar: {exc}"}
    if not models:
        return {"healthy": False, "detail": "Erreichbar, aber es ist kein Modell geladen."}
    if config.LM_STUDIO_MODEL and config.LM_STUDIO_MODEL not in models:
        return {
            "healthy": True,
            "detail": f"Erreichbar — {config.LM_STUDIO_MODEL} ist dort aber nicht geladen. Geladen: {', '.join(models[:5])}",
        }
    return {"healthy": True, "detail": f"Erreichbar ({len(models)} Modell(e) geladen)."}


def _local_subnet() -> ipaddress.IPv4Network | None:
    """Best-effort guess at the LAN /24 this machine is on, via the classic
    UDP-connect trick — connect() on a UDP socket never actually sends a
    packet, it just makes the OS pick and report the source IP/interface it
    WOULD use for that destination, which is exactly the LAN-facing IP we
    want. 8.8.8.8 is only ever used as a routable-looking target, nothing is
    sent to it."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ipaddress.ip_network(f"{ip}/24", strict=False)
    except OSError:
        return None


async def _port_open(ip: str, port: int, timeout: float) -> bool:
    """Fast concurrent reachability check — just the TCP handshake, no HTTP
    yet. Cheap enough to run against all 254 hosts of a /24 at once."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def _validate_lm_studio(ip: str, port: int) -> dict | None:
    """Confirms a host with an open port is actually LM Studio (not some
    unrelated service that happens to listen on 1234) by asking for its
    model list — run via asyncio.to_thread since `requests` is synchronous
    and this only ever runs for the handful of hosts whose port answered."""
    try:
        resp = requests.get(f"http://{ip}:{port}/v1/models", timeout=2.5)
        resp.raise_for_status()
        models = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
    except (requests.RequestException, ValueError):
        return None
    return {"ip": ip, "url": f"http://{ip}:{port}/v1", "models": models}


# Ports gängiger lokaler LLM-Server, für die "erweiterte Suche" (der
# normale Scan prüft nur den LM-Studio-Standardport 1234 — reicht nicht,
# wenn LM Studio auf einem anderen Port läuft oder ein anderer Server
# gemeint ist). Alle unten sind bekannt dafür, eine OpenAI-kompatible
# /v1/models-Route anzubieten (Ollama seit 0.1.26, text-generation-webuis
# OpenAI-Extension, koboldcpp, LocalAI, vLLM, ...), sonst würde
# _validate_lm_studio() sie ohnehin als "kein Treffer" verwerfen.
EXTENDED_SCAN_PORTS = [1234, 11434, 5000, 5001, 7860, 8000, 8080, 4891, 1337]


@app.post("/model/scan")
async def model_scan(body: dict | None = None):
    """Scans the local /24 subnet for a reachable LM Studio (or other
    OpenAI-compatible local LLM server) instance, streaming NDJSON progress
    events so the frontend can show a real progress bar instead of a blind
    spinner (see the js-scan-* wiring in claude-app.js). Two phases: a fast
    concurrent TCP-connect sweep across every (host, port) combination
    (bounded concurrency), then an actual GET /v1/models against every
    target whose port answered — there are only ever a handful of those —
    to confirm it's really an LLM server and read its model list.

    body.ports (optional): which ports to probe per host. Defaults to just
    the LM Studio default (1234, single quick scan); the frontend's
    "Erweiterte Suche" button passes EXTENDED_SCAN_PORTS instead.
    """
    ports = (body or {}).get("ports")
    if not ports:
        ports = [int((body or {}).get("port") or 1234)]
    ports = sorted({int(p) for p in ports})
    network = _local_subnet()

    async def gen():
        if network is None:
            yield json.dumps({"type": "error", "message": "Konnte das lokale Netzwerk nicht bestimmen."}) + "\n"
            return
        hosts = [str(h) for h in network.hosts()]
        targets = [(h, p) for h in hosts for p in ports]
        total = len(targets)
        yield json.dumps({"type": "start", "total": total, "subnet": str(network), "ports": ports}) + "\n"

        queue: asyncio.Queue = asyncio.Queue()
        sem = asyncio.Semaphore(96)

        async def probe(ip: str, port: int) -> None:
            async with sem:
                ok = await _port_open(ip, port, 0.3)
            await queue.put((ip, port) if ok else None)

        tasks = [asyncio.create_task(probe(ip, p)) for ip, p in targets]
        scanned = 0
        open_targets: list[tuple[str, int]] = []
        # Feste Anzahl Zwischen-Updates statt fixer Schrittweite - bei
        # mehreren Ports (erweiterte Suche) sind das leicht über 2000 Ziele,
        # "alle 4" wäre dort über 500 NDJSON-Zeilen für den Fortschrittsbalken.
        step = max(1, total // 60)
        while scanned < total:
            item = await queue.get()
            scanned += 1
            if item:
                open_targets.append(item)
            if scanned % step == 0 or scanned == total:
                yield json.dumps({"type": "progress", "phase": "scan", "scanned": scanned, "total": total}) + "\n"
        await asyncio.gather(*tasks)

        if not open_targets:
            yield json.dumps({"type": "done", "found": []}) + "\n"
            return

        found = []
        for i, (ip, port) in enumerate(open_targets):
            result = await asyncio.to_thread(_validate_lm_studio, ip, port)
            if result:
                found.append(result)
                yield json.dumps({"type": "found", **result}) + "\n"
            yield json.dumps(
                {"type": "progress", "phase": "validate", "scanned": i + 1, "total": len(open_targets)}
            ) + "\n"
        yield json.dumps({"type": "done", "found": found}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class UnloadModelRequest(BaseModel):
    model: str


@app.post("/model/force-load")
def model_force_load():
    """"Trotzdem laden" — the user overrides hardware.py's memory guard for
    the currently configured model. Used from the chat's inline warning card
    when the check turns out to be wrong for this machine (e.g. the model
    actually fits fine in practice) or the user accepts the risk anyway.

    Best-effort actively loads the model right now via LM Studio's own v1
    REST API (POST /api/v1/models/load — works over the network just like
    every other LM Studio call this app makes), instead of only clearing the
    guard and hoping the next chat request's just-in-time load succeeds.
    Failing that call is not fatal: unblock_all() always runs, so the normal
    JIT-on-next-request path still gets a chance."""
    try:
        requests.post(
            f"{hardware.lm_studio_root()}/api/v1/models/load",
            json={"model": config.LM_STUDIO_MODEL}, timeout=120,
        )
    except requests.RequestException as exc:
        print(f"[model] /api/v1/models/load für {config.LM_STUDIO_MODEL} fehlgeschlagen ({exc}), JIT-Laden bleibt als Fallback.")
    hardware.unblock_all()
    return {"ok": True}


@app.get("/model/loaded")
def model_loaded():
    """Every model LM Studio currently has resident in memory, for the
    "andere Modelle entladen" list next to the hardware-guard warning."""
    return {"models": hardware.loaded_models_info()}


@app.post("/model/unload")
def model_unload(req: UnloadModelRequest):
    """Ejects one loaded model to free memory (see hardware.loaded_models_info)
    and re-opens the hardware guard afterwards, in case freeing it is now
    enough for the model Jarvis actually wants to load."""
    llm_client.eject_model(req.model)
    hardware.unblock_all()
    return {"ok": True}


@app.post("/settings")
def update_settings(req: UpdateSettingsRequest):
    if req.lm_studio_base_url is not None and req.lm_studio_base_url.strip():
        config.set_lm_studio_base_url(req.lm_studio_base_url.strip())
    for name in config.get_simple_settings():
        value = getattr(req, name)
        if value is not None:
            config.set_simple_setting(name, value.strip())
    if req.whisper_model is not None and req.whisper_model.strip():
        stt.reset_model()
    if req.supertonic_voice is not None and req.supertonic_voice.strip():
        tts.reset_supertonic_voice()
    if req.deepseek_enabled is not None:
        config.set_deepseek_enabled(req.deepseek_enabled)
    return {
        "lm_studio_base_url": config.LM_STUDIO_BASE_URL,
        "deepseek_enabled": config.DEEPSEEK_ENABLED,
        **config.get_simple_settings(),
    }


@app.get("/models")
def list_models():
    # Welches Modell gerade tatsächlich antwortet, spiegelt _request_targets()
    # wider: "lmstudio" pinnt explizit auf LM Studio, alles andere ("auto"
    # das Default-Verhalten, oder "deepseek" explizit) bevorzugt DeepSeek,
    # sobald ein Key konfiguriert ist. Vorher stand hier immer
    # LM_STUDIO_MODEL, auch wenn DeepSeek die Anfragen tatsächlich beantwortet
    # hat - die Modellauswahl zeigte dann nie den wirklich aktiven Stand an.
    active_is_deepseek = bool(config.DEEPSEEK_API_KEY) and config.DEEPSEEK_ENABLED and config.ACTIVE_PROVIDER != "lmstudio"
    current = f"{llm_client.DEEPSEEK_MODEL_ID_PREFIX}{config.DEEPSEEK_MODEL}" if active_is_deepseek else config.LM_STUDIO_MODEL
    try:
        model_ids = llm_client.list_models()
        caps = llm_client.list_model_capabilities()
        fit = hardware.check_models(
            list(dict.fromkeys([*model_ids, config.LM_STUDIO_MODEL])),
            freeable_ids=[config.LM_STUDIO_MODEL],
        )
        # DeepSeek ist eine Cloud-API, kein lokales Modell - hardware.py's
        # Speicher-Check hat dazu nichts zu sagen, immer "passt".
        if active_is_deepseek:
            fit.setdefault(current, {"fits": True, "fits_now": True, "needed_bytes": 0})
        return {
            "models": model_ids,
            "current": current,
            "model_caps": caps,
            "current_caps": caps.get(current, []),
            "model_fit": fit,
            "current_fit": (
                {"fits": True, "message": None} if active_is_deepseek else
                {
                    "fits": not hardware.blocked_reason(config.LM_STUDIO_MODEL),
                    "message": hardware.blocked_reason(config.LM_STUDIO_MODEL),
                }
            ),
        }
    except requests.RequestException as exc:
        return {"models": [], "current": current, "error": str(exc)}


@app.post("/models/select")
def select_model(req: SelectModelRequest):
    # DeepSeek ausgewählt (siehe llm_client.list_models/is_deepseek_model_id)
    # - kein LM-Studio-Modell, also nichts von der Speicher-/Eject-Logik
    # unten anwenden, nur explizit auf diesen Provider umschalten. Vorher
    # gab es dafür gar keinen Auswahl-Weg: DeepSeek tauchte im Picker nicht
    # auf, und ein LM-Studio-Pick änderte am tatsächlich aktiven Provider
    # nichts, solange ein DeepSeek-Key konfiguriert war (ACTIVE_PROVIDER
    # blieb immer "auto", das Default bevorzugt DeepSeek bedingungslos).
    if llm_client.is_deepseek_model_id(req.model):
        if not config.DEEPSEEK_API_KEY:
            return {"ok": False, "error": "Kein DeepSeek-API-Key konfiguriert.", "current": config.LM_STUDIO_MODEL, "model": req.model}
        if not config.DEEPSEEK_ENABLED:
            return {"ok": False, "error": "DeepSeek ist gerade ausgeschaltet — in den Einstellungen wieder aktivieren.", "current": config.LM_STUDIO_MODEL, "model": req.model}
        config.set_provider("deepseek")
        return {"ok": True}
    # Ein echtes LM-Studio-Modell ausgewählt: explizit auf "lmstudio" pinnen,
    # sonst würde ein weiterhin konfigurierter DeepSeek-Key diese Wahl im
    # nächsten Request wieder überstimmen (siehe _request_targets).
    previous_model = config.LM_STUDIO_MODEL
    fit = hardware.check_model(req.model, freeable_ids=[previous_model])
    if not fit["fits"] and not req.force:
        print(f"[model] {fit['message']}")
        return {"ok": False, "error": fit["message"], "current": previous_model, "model": req.model}
    config.set_provider("lmstudio")
    # Fits only once the previous model is out of memory: unload it BEFORE
    # loading the new one. The usual load-then-unload order (below) would
    # briefly hold both, which is exactly the overload this check prevents.
    eject_first = not fit["fits_now"] and previous_model and previous_model != req.model
    hardware.unblock_all()
    config.set_model(req.model)
    llm_client._note_active_target(config.LM_STUDIO_BASE_URL, req.model)

    def _switch():
        if eject_first:
            llm_client.eject_model(previous_model)
        # A minimal completion request is what actually makes LM Studio's
        # just-in-time loading load the new model — it won't otherwise
        # happen until the next real chat turn. Only once that succeeds is
        # the previous model explicitly ejected (see llm_client.eject_model)
        # — JIT loading alone was observed to leave it resident in VRAM
        # instead of reliably swapping it out, so without this, switching
        # models left both loaded at the same time. Ejecting only after
        # the new one is confirmed up avoids a gap with nothing loaded at
        # all if the new model fails to load. All fire-and-forget in a
        # background thread so this route returns immediately instead of
        # blocking on however long the model takes to load.
        try:
            requests.post(
                f"{config.LM_STUDIO_BASE_URL}/chat/completions",
                json={"model": req.model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=120,
            ).raise_for_status()
        except requests.RequestException as exc:
            print(f"[model] Warmladen von {req.model} fehlgeschlagen: {exc}")
            return
        if not eject_first and previous_model and previous_model != req.model:
            llm_client.eject_model(previous_model)

    threading.Thread(target=_switch, daemon=True).start()
    return {"ok": True}


@app.get("/browser/status")
def browser_status():
    return {"connected": browser_agent.agent.connected()}


@app.get("/browser/poll")
def browser_poll():
    """Long-lived Chrome extension fetches its queued commands here."""
    return {"commands": browser_agent.agent.poll()}


@app.post("/browser/result")
def browser_result(result: BrowserResult):
    accepted = browser_agent.agent.resolve(result.id, result.model_dump())
    return {"accepted": accepted}


@app.get("/fillers")
def get_fillers():
    return {"fillers": filler_urls, "thinking_filler": thinking_filler_url}


@app.post("/trigger")
async def trigger():
    """Called by the global hotkey listener to wake up connected frontends."""
    await broadcast({"type": "wake"})
    return {"notified": len(active_sockets)}


# ---------------------------------------------------------------------------
# Code-Tab: the real OpenCode TUI streamed into an embedded xterm.js terminal.
# The browser opens /code/tty/ws; the server spawns `opencode <dir>` on a PTY
# (see backend/opencode_agent.start_tty) and pumps raw bytes both ways.
# ---------------------------------------------------------------------------


@app.get("/code/status")
def code_status():
    """Everything the frontend needs to render the Code-Tab: which coding
    agent is selected (opencode/claude/codex) and which are installed, the LM
    Studio model list (with loaded context, opencode only), the current/
    default model and the working directory. Also refreshes the opencode
    provider config so the models opencode knows about stay in sync with what
    LM Studio reports."""
    agent = opencode_agent.get_code_agent()
    # LM Studio wiring only means anything for opencode — claude/codex bring
    # their own model config and don't read LM Studio at all.
    models = opencode_agent.list_models() if agent == "opencode" else []
    default = opencode_agent.default_model() if agent == "opencode" else ""
    if models:
        opencode_agent.ensure_provider_config(models, opencode_agent.startup_model())
    return {
        "model": config.LM_STUDIO_MODEL,
        "default": default,
        "dir": opencode_agent.get_code_dir(),
        "models": models,
        "min_context": opencode_agent.CODE_MIN_CONTEXT,
        "agent": agent,
        "agents": opencode_agent.list_code_agents(),
    }


@app.post("/code/config")
def code_set_config(body: dict):
    """Persist the Code-Tab working directory and/or the selected coding agent."""
    new_dir = str(body.get("dir", "")).strip()
    if new_dir:
        opencode_agent.set_code_dir(new_dir)
    new_agent = str(body.get("agent", "")).strip()
    if new_agent:
        try:
            opencode_agent.set_code_agent(new_agent)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unbekannter Coding-Agent: {new_agent!r}")
    return {"dir": opencode_agent.get_code_dir(), "agent": opencode_agent.get_code_agent()}


@app.get("/code/sessions")
def code_sessions():
    """Real opencode sessions (from opencode's own SQLite store), most recent
    first — the Code-Tab sidebar shows these instead of JARVIS chat
    conversations, since the two are unrelated (see opencode_agent.list_recent_sessions).
    Claude Code and Codex keep their own session history outside JARVIS
    entirely (`claude --resume`/`codex resume` pickers), so there is nothing
    to list here for them."""
    if opencode_agent.get_code_agent() != "opencode":
        return {"sessions": []}
    wdir = opencode_agent.get_code_dir()
    return {"sessions": opencode_agent.list_recent_sessions(directory=wdir)}


@app.delete("/code/sessions/{session_id}")
def code_session_delete(session_id: str):
    """Delete a real opencode session (via `opencode session delete`)."""
    ok = opencode_agent.delete_session(session_id)
    return {"ok": ok}


@app.patch("/code/sessions/{session_id}")
def code_session_rename(session_id: str, req: RenameCodeSessionRequest):
    """Rename a real opencode session (updates its title in opencode's own store)."""
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Titel darf nicht leer sein")
    ok = opencode_agent.rename_session(session_id, title)
    return {"ok": ok}


@app.websocket("/code/tty/ws")
async def code_tty_ws(websocket: WebSocket):
    """Pipe the real OpenCode TUI into an embedded xterm.js terminal.

    Protocol (all frames on one connection, freed of the old JSON chat):
      Server → Client: binary frames = raw PTY bytes; then one text frame
        {"type":"exit","code":...} when the TUI exits, and the socket closes.
      Client → Server: binary frames = keystrokes/bytes written to the PTY
        stdin; text frame {"type":"resize","cols":N,"rows":N} to resize the PTY.

    A single background "sender" task drains an asyncio queue so every PTY→WS
    write happens from one coroutine (Starlette's WebSocket does not allow
    concurrent sends), while the input/resize receive loop stays independent.
    """
    await websocket.accept()
    wdir = opencode_agent.get_code_dir()
    session_id = websocket.query_params.get("session_id") or None
    try:
        opencode_agent.reset_output()
        tty = opencode_agent.start_tty(wdir, session_id=session_id)
    except (RuntimeError, OSError) as exc:
        # RuntimeError: z.B. kein PTY auf diesem OS (Windows).
        # OSError (u.a. FileNotFoundError): OPENCODE_BIN existiert nicht,
        # z.B. weil die JARVIS-Code-Binary nach einem frischen `git clone`
        # noch nicht gebaut wurde (siehe SETUP.md). Ohne diesen Fang bliebe
        # der Client bei "verbinde" hängen, statt eine Fehlermeldung zu sehen.
        await websocket.send_text(json.dumps({"type": "exit", "code": None, "error": str(exc)}))
        await websocket.close()
        return
    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    # Per-connection state: the terminal queries we must answer (see
    # answer_terminal_queries) and the last reported PTY size for XTREPORTWIN.
    tty_state: dict = {"cols": 80, "rows": 24}

    def _reader() -> None:
        """Blocking PTY reader: answer OpenTUI queries, forward raw bytes."""
        try:
            while True:
                data = tty.read(65536)
                if not data:
                    break
                opencode_agent.answer_terminal_queries(tty, data, tty_state)
                # Mitschneiden, damit Jarvis sagen kann, was opencode gerade
                # tut (Tool "opencode_status") — der Browser ist sonst der
                # Einzige, der die Ausgabe je zu sehen bekommt.
                opencode_agent.note_output(data)
                loop.call_soon_threadsafe(out_q.put_nowait, ("data", data))
        except OSError:
            pass
        finally:
            loop.call_soon_threadsafe(out_q.put_nowait, ("exit", tty.poll()))

    threading.Thread(target=_reader, daemon=True).start()

    async def _sender() -> None:
        try:
            while True:
                kind, payload = await out_q.get()
                if kind == "data":
                    await websocket.send_bytes(payload)
                else:  # exit
                    await websocket.send_text(json.dumps({"type": "exit", "code": payload}))
                    break
        finally:
            # Let the receive loop wake, then close the connection for good.
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001 - already closing; best effort
                pass

    sender_task = asyncio.create_task(_sender())

    def _cleanup() -> None:
        opencode_agent.kill_tty(tty)
        tty.close()

    try:
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                try:
                    tty.write(msg["bytes"])
                except OSError:
                    break
            elif msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
                if data.get("type") == "resize":
                    cols = int(data.get("cols") or 80)
                    rows = int(data.get("rows") or 24)
                    tty_state["cols"] = cols
                    tty_state["rows"] = rows
                    opencode_agent.resize_tty(tty, cols, rows)
    except WebSocketDisconnect:
        pass
    finally:
        _cleanup()
        sender_task.cancel()
        try:
            await sender_task
        except (asyncio.CancelledError, RuntimeError):
            pass


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_sockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_sockets:
            active_sockets.remove(websocket)


@app.websocket("/browser/ws")
async def browser_ws(websocket: WebSocket):
    """Persistent command channel for the local Jarvis Chrome extension."""
    await websocket.accept()
    browser_agent.agent.connect(websocket, asyncio.get_running_loop())
    try:
        while True:
            result = await websocket.receive_json()
            if result.get("type") == "heartbeat":
                browser_agent.agent.heartbeat()
                continue
            browser_agent.agent.resolve(result.get("id", ""), result)
    except WebSocketDisconnect:
        browser_agent.agent.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=config.JARVIS_HOST, port=config.JARVIS_PORT)
