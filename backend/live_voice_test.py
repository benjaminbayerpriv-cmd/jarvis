"""Standalone test: talk to Gemini Live (real speech-to-speech) through the
mic and hear it reply through the speakers.

This is deliberately NOT wired into Jarvis's normal chat/TTS pipeline — it's
a separate proof-of-concept to test whether the Live API is a viable
replacement before touching anything that already works. Run directly:

    .venv/bin/python3 -m backend.live_voice_test
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue

import sounddevice as sd
import websockets

from . import config

MODEL = "models/gemini-2.5-flash-native-audio-latest"
URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    f"?key={config.GEMINI_API_KEY}"
)

INPUT_RATE = 16000  # required by the Live API for mic input
OUTPUT_RATE = 24000  # fixed output rate the API always uses
DURATION_S = 45


async def run() -> None:
    mic_queue: "queue.Queue[bytes | None]" = queue.Queue()
    loop = asyncio.get_event_loop()

    def on_audio(indata, frames, time_info, status) -> None:
        mic_queue.put(bytes(indata))

    playback = sd.RawOutputStream(samplerate=OUTPUT_RATE, channels=1, dtype="int16")
    playback.start()
    mic_stream = sd.RawInputStream(
        samplerate=INPUT_RATE, channels=1, dtype="int16", callback=on_audio, blocksize=1600
    )

    async with websockets.connect(URL, open_timeout=15) as ws:
        setup = {
            "setup": {
                "model": MODEL,
                "generationConfig": {"responseModalities": ["AUDIO"]},
                "systemInstruction": {
                    "parts": [{"text": "Du bist Jarvis, ein hilfreicher deutscher Assistent. Antworte auf Deutsch, kurz und direkt."}]
                },
                "inputAudioTranscription": {},
                "outputAudioTranscription": {},
            }
        }
        await ws.send(json.dumps(setup))
        await ws.recv()  # setupComplete
        print(f"[live-test] Verbunden. Sprich jetzt ins Mikrofon — {DURATION_S}s Testfenster.", flush=True)
        mic_stream.start()

        async def sender():
            while True:
                chunk = await loop.run_in_executor(None, mic_queue.get)
                if chunk is None:
                    return
                msg = {
                    "realtimeInput": {
                        "audio": {
                            "data": base64.b64encode(chunk).decode("ascii"),
                            "mimeType": f"audio/pcm;rate={INPUT_RATE}",
                        }
                    }
                }
                await ws.send(json.dumps(msg))

        async def receiver():
            async for raw in ws:
                data = json.loads(raw)
                sc = data.get("serverContent", {})
                if t := sc.get("inputTranscription", {}).get("text", ""):
                    print("[live-test] DU:", t, flush=True)
                if t := sc.get("outputTranscription", {}).get("text", ""):
                    print("[live-test] JARVIS:", t, flush=True)
                for part in sc.get("modelTurn", {}).get("parts", []):
                    if "inlineData" in part:
                        audio = base64.b64decode(part["inlineData"]["data"])
                        await loop.run_in_executor(None, playback.write, audio)

        sender_task = asyncio.create_task(sender())
        receiver_task = asyncio.create_task(receiver())

        await asyncio.sleep(DURATION_S)

        mic_stream.stop()
        mic_queue.put(None)
        sender_task.cancel()
        receiver_task.cancel()
        playback.stop()
        print("[live-test] Testfenster beendet.", flush=True)


if __name__ == "__main__":
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY ist nicht gesetzt.")
    asyncio.run(run())
