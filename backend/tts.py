"""Speech output, with fallbacks that keep Jarvis talking.

Supertonic is the primary voice: a local, offline, unlimited neural TTS
model that sounds far better than the old OS-builtin voice ever did, with
no per-character cost or quota. If it can't load (e.g. first run with no
internet to fetch the model), this falls back to ElevenLabs when a key is
configured (free tier is 10k characters a month and runs dry without
warning), and finally to the voice built into the operating system — worse
sounding, but free, offline and always available: macOS's built-in `say`,
the SAPI synthesizer (via PowerShell, no extra dependency needed) on
Windows. Silence is the one outcome that makes Jarvis look broken.
"""

from __future__ import annotations

import io
import platform
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import requests
from supertonic import TTS

from . import config, platform_utils

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

MACOS_VOICE = "Anna"

IS_WINDOWS = platform.system() == "Windows"

# Set once ElevenLabs reports quota exhaustion, so we stop paying the
# latency of a doomed request on every single sentence.
_elevenlabs_blocked = False

# Supertonic loads a model from disk (slow-ish), so it's built once, lazily,
# and reused for every request rather than per-call.
_supertonic_lock = threading.Lock()
_supertonic_tts: TTS | None = None
_supertonic_style = None

# File extension + mime type produced by each engine, so callers (the /tts
# route, the filler cache) don't need their own platform checks.
ENGINE_MEDIA = {
    "supertonic": ("wav", "audio/wav"),
    "elevenlabs": ("mp3", "audio/mpeg"),
    "macos": ("m4a", "audio/mp4"),
    "windows": ("wav", "audio/wav"),
}


class VoiceInfo:
    """Which engine produced the last clip, for the UI to mention."""

    engine = "elevenlabs"


def _macos_say(text: str) -> bytes:
    out = Path(tempfile.mkdtemp()) / "say.m4a"
    subprocess.run(
        ["say", "-v", MACOS_VOICE, "--file-format=m4af", "--data-format=aac",
         "-o", str(out), text],
        check=True,
        capture_output=True,
        timeout=60,
    )
    data = out.read_bytes()
    try:
        out.unlink()
        out.parent.rmdir()
    except OSError:
        pass
    return data


def _windows_say(text: str) -> bytes:
    """Render text via the SAPI synthesizer built into Windows. The text is
    piped over stdin (rather than interpolated into the script) so quotes
    and special characters in it can't break out of the PowerShell command."""
    out = Path(tempfile.mkdtemp()) / "say.wav"
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{out}'); "
        "$s.Speak([Console]::In.ReadToEnd()); "
        "$s.Dispose()"
    )
    subprocess.run(
        platform_utils.powershell(script),
        input=text,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    data = out.read_bytes()
    try:
        out.unlink()
        out.parent.rmdir()
    except OSError:
        pass
    return data


def _local_say(text: str) -> bytes:
    if IS_WINDOWS:
        VoiceInfo.engine = "windows"
        return _windows_say(text)
    VoiceInfo.engine = "macos"
    return _macos_say(text)


def _elevenlabs(text: str) -> bytes:
    url = ELEVENLABS_URL.format(voice_id=config.ELEVENLABS_VOICE_ID)
    resp = requests.post(
        url,
        headers={
            "xi-api-key": config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.75,
                "speed": 0.9,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def _get_supertonic() -> tuple[TTS, object]:
    """Load the Supertonic model and voice style once, then reuse them.
    Thread-safe since FastAPI's sync endpoints run each request in a
    worker thread."""
    global _supertonic_tts, _supertonic_style
    if _supertonic_tts is None:
        with _supertonic_lock:
            if _supertonic_tts is None:
                tts = TTS(auto_download=True)
                _supertonic_style = tts.get_voice_style(voice_name=config.SUPERTONIC_VOICE)
                _supertonic_tts = tts
    return _supertonic_tts, _supertonic_style


def _supertonic_say(text: str) -> bytes:
    tts, style = _get_supertonic()
    # FastAPI runs sync endpoints in a thread pool, and it's undocumented
    # whether one Supertonic engine tolerates concurrent synthesize() calls
    # from different threads — e.g. the startup filler-generation pass
    # overlapping a live chat reply. Observed live: intermittent silent
    # failures here that fell through to the macOS voice. Serializing every
    # call through the one shared engine costs nothing perceptible (each
    # call is already sub-second) and removes the race entirely.
    with _supertonic_lock:
        wav, _duration = tts.synthesize(text=text, lang=config.SUPERTONIC_LANG, voice_style=style)
    samples = np.clip(np.asarray(wav).squeeze(), -1.0, 1.0)
    pcm16 = (samples * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(tts.sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def synthesize(text: str) -> bytes:
    """Return spoken audio for `text`. Never raises for ordinary failures —
    silence is the one outcome that makes Jarvis look broken."""
    global _elevenlabs_blocked

    try:
        audio = _supertonic_say(text)
        VoiceInfo.engine = "supertonic"
        return audio
    except Exception as exc:  # noqa: BLE001 - fall through to ElevenLabs/OS
        print(f"[tts] Supertonic nicht verfügbar, nutze Ausweich-Stimme: {exc}")

    if config.ELEVENLABS_API_KEY and not _elevenlabs_blocked:
        try:
            audio = _elevenlabs(text)
            VoiceInfo.engine = "elevenlabs"
            return audio
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = (exc.response.text if exc.response is not None else "")[:200]
            # 401 = bad key, 429 = rate limited. Quota exhaustion arrives as
            # a 401 with quota_exceeded in the body.
            if status in (401, 402, 429) or "quota" in body.lower():
                _elevenlabs_blocked = True
                print(f"[tts] ElevenLabs nicht verfügbar ({status}), nutze lokale Stimme. {body}")
        except requests.RequestException as exc:
            print(f"[tts] ElevenLabs Netzwerkfehler, nutze lokale Stimme: {exc}")

    return _local_say(text)
