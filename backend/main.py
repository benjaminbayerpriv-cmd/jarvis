from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import requests
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import browser_agent, config, fillers, llm_client, memory, panel, tts

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
    loop.create_task(_pump_panel())


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


class ChatResponse(BaseModel):
    reply: str


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


@app.get("/")
def serve_index():
    html = (FRONTEND_DIR / "index.html").read_text()
    html = html.replace("/static/style.css", f"/static/style.css?v={_BUILD}")
    html = html.replace("/static/app.js", f"/static/app.js?v={_BUILD}")
    return HTMLResponse(html, headers=_NO_CACHE)


class NoCacheStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(_NO_CACHE)
        return resp


app.mount("/static", NoCacheStatic(directory=FRONTEND_DIR), name="static")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        reply = llm_client.get_reply(req.message, req.history)
    except (requests.RequestException, llm_client.ModelError):
        reply = (
            "Ich komm gerade nicht an mein Sprachmodell ran. "
            "Läuft LM Studio und ist der Server dort gestartet?"
        )
    return ChatResponse(reply=reply)


@app.post("/tts")
def speak(req: ChatResponse):
    try:
        audio = tts.synthesize(req.reply)
    except Exception:
        return Response(status_code=502, content=b"")
    mime = "audio/mp4" if tts.VoiceInfo.engine == "macos" else "audio/wav" if tts.VoiceInfo.engine == "windows" else "audio/mpeg"
    return Response(content=audio, media_type=mime)


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Streams the reply as newline-delimited JSON, one line per sentence,
    each carrying that sentence's already-synthesized audio — so playback
    can start after the first sentence instead of waiting for the whole
    reply plus a single big TTS call."""

    def generate():
        full_text = ""
        try:
            for event in llm_client.stream_reply(req.message, req.history):
                if event["type"] == "sentence":
                    text = event["text"]
                    # Speech is optional; the words are not. If synthesis
                    # fails the sentence still goes out silently, because
                    # dropping it made Jarvis look completely dead.
                    audio_b64 = ""
                    mime = "audio/mpeg"
                    try:
                        audio = tts.synthesize(text)
                        audio_b64 = base64.b64encode(audio).decode("ascii")
                        if tts.VoiceInfo.engine == "macos":
                            mime = "audio/mp4"
                        elif tts.VoiceInfo.engine == "windows":
                            mime = "audio/wav"
                    except Exception as exc:  # noqa: BLE001 - never mute the reply
                        print(f"[tts] Sprachausgabe fehlgeschlagen: {exc}")
                    yield json.dumps(
                        {"type": "sentence", "text": text, "audio": audio_b64, "mime": mime}
                    ) + "\n"
                elif event["type"] == "done":
                    full_text = event["full_text"]
                    yield json.dumps({"type": "done", "full_text": event["full_text"]}) + "\n"
            if full_text:
                memory.log_summary(req.message, full_text)
        except (requests.RequestException, llm_client.ModelError, KeyError, IndexError) as exc:
            fallback = (
                "Ich komme gerade nicht an mein Sprachmodell ran. "
                "Prüfe bitte, ob Gemma 4 E4B in LM Studio geladen ist."
            )
            print(f"[model] Anfrage fehlgeschlagen: {exc}")
            try:
                audio_b64 = base64.b64encode(tts.synthesize(fallback)).decode("ascii")
                yield json.dumps({"type": "sentence", "text": fallback, "audio": audio_b64}) + "\n"
            except requests.RequestException:
                yield json.dumps({"type": "sentence", "text": fallback, "audio": ""}) + "\n"
            yield json.dumps({"type": "done", "full_text": fallback}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


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
