from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import time
from pathlib import Path

import requests
from fastapi import FastAPI, File, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import browser_agent, config, conversations, fillers, llm_client, memory, opencode_agent, panel, projects, stt, transcript_log, tts, vector_memory

app = FastAPI(title="Jarvis")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local Chrome extension uses a generated chrome-extension:// origin
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

active_sockets: list[WebSocket] = []
filler_urls: list[str] = []


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
    global filler_urls
    memory.initialize()
    healthy, detail = llm_client.model_health()
    print(f"[model] {detail}")
    if not healthy:
        panel.push("notify", text=detail)

    def _generate():
        global filler_urls
        filler_urls = fillers.ensure_fillers()

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


class CancelRequest(BaseModel):
    turn_id: str


class SelectModelRequest(BaseModel):
    model: str


class CreateProjectRequest(BaseModel):
    dir: str
    name: str = ""
    description: str = ""
    tag: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


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


@app.get("/")
def serve_index():
    # The start page is the real claude.ai UI: the SSR snapshot of the
    # Anthropic web client (frontend/claude.html), with every Anthropic asset
    # localized under /static/vendor/ap/ and the client scripts stripped so the
    # logged-in interface renders as static HTML+CSS instead of bouncing to a
    # /login 404 (see _freeze_snapshot). The previous JARVIS UI still lives at
    # frontend/index.html (with its own style.css/app.js) and remains reachable
    # via the /static/* mount for reference, but is no longer served on /.
    #
    # Explicit encoding matters here: Path.read_text() defaults to the OS
    # locale's preferred encoding, which is cp1252 on German Windows, not
    # UTF-8 — the file itself is UTF-8, so without this every special
    # character in it (observed live: the "≡" debug-toggle symbol) gets
    # silently mangled into mojibake before it's ever served to the browser.
    html = (FRONTEND_DIR / "claude.html").read_text(encoding="utf-8")
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
        '    <link rel="stylesheet" href="/static/xterm.css?v={}\">\n'.format(_BUILD)
        + '    <script src="/static/xterm.js?v={}"></script>\n'.format(_BUILD)
        + '    <script src="/static/xterm-addon-fit.js?v={}"></script>\n'.format(_BUILD)
        + '    <script src="/static/claude-app.js?v={}"></script>\n'.format(_BUILD)
    )
    html = html.replace("</body>", f"{assets}  </body>")
    return HTMLResponse(html, headers=_NO_CACHE)


@app.get("/favicon.ico")
def favicon():
    """Serve the real Claude icon at the browser's default probe path so the
    frozen snapshot is completely free of 404s (the SSR markup links its
    shortcut icon to /favicon.ico, and Chrome probes it regardless of the
    rel="icon" SVG it also links)."""
    icon = FRONTEND_DIR / "vendor" / "ap" / "cd02a42d9-Vq_H3mgS.svg"
    if icon.exists():
        return Response(icon.read_bytes(), media_type="image/svg+xml")
    return Response(status_code=204)


class NoCacheStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(_NO_CACHE)
        return resp


app.mount("/static", NoCacheStatic(directory=FRONTEND_DIR), name="static")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        reply = llm_client.get_reply(req.message, req.history, req.mode)
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
            for event in llm_client.stream_reply(req.message, req.history, turn_id=req.turn_id, mode=req.mode, images=req.images):
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
                    try:
                        audio = tts.synthesize(text)
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
                "I can't reach my language model right now. "
                "Please check whether Gemma is loaded in LM Studio."
            )
            print(f"[model] Anfrage fehlgeschlagen: {exc}")
            try:
                audio_b64 = base64.b64encode(tts.synthesize(fallback)).decode("ascii")
                yield json.dumps({"type": "sentence", "text": fallback, "audio": audio_b64}) + "\n"
            except requests.RequestException:
                yield json.dumps({"type": "sentence", "text": fallback, "audio": ""}) + "\n"
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
    updated = projects.update(project_id, req.name, req.description)
    if updated is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return updated


@app.delete("/projects/{project_id}")
def delete_project(project_id: str):
    projects.delete(project_id)
    return {"ok": True}


@app.get("/models")
def list_models():
    try:
        model_ids = llm_client.list_models()
        caps = llm_client.list_model_capabilities()
        return {
            "models": model_ids,
            "current": config.LM_STUDIO_MODEL,
            "model_caps": caps,
            "current_caps": caps.get(config.LM_STUDIO_MODEL, []),
        }
    except requests.RequestException as exc:
        return {"models": [], "current": config.LM_STUDIO_MODEL, "error": str(exc)}


@app.post("/models/select")
def select_model(req: SelectModelRequest):
    previous_model = config.LM_STUDIO_MODEL
    config.set_model(req.model)
    llm_client._note_active_target(config.LM_STUDIO_BASE_URL, req.model)

    def _switch():
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
        if previous_model and previous_model != req.model:
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
    return {"fillers": filler_urls}


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
    """Everything the frontend needs to render the Code-Tab: the LM Studio
    model list (with loaded context), the current/default model and the
    working directory. Also refreshes the opencode provider config so the
    models opencode knows about stay in sync with what LM Studio reports."""
    models = opencode_agent.list_models()
    default = opencode_agent.default_model()
    if models:
        opencode_agent.ensure_provider_config(models, default)
    return {
        "model": config.LM_STUDIO_MODEL,
        "default": default,
        "dir": opencode_agent.get_code_dir(),
        "models": models,
        "min_context": opencode_agent.CODE_MIN_CONTEXT,
    }


@app.post("/code/config")
def code_set_config(body: dict):
    """Persist the Code-Tab working directory."""
    new_dir = str(body.get("dir", "")).strip()
    if new_dir:
        opencode_agent.set_code_dir(new_dir)
    return {"dir": opencode_agent.get_code_dir()}


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
    try:
        tty = opencode_agent.start_tty(wdir)
    except RuntimeError as exc:
        # e.g. no PTY on this OS (Windows) — tell the client plainly instead
        # of letting the exception surface as a raw traceback in the log.
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
