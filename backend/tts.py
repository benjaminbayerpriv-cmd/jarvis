"""Speech output, with a fallback that keeps Jarvis talking.

ElevenLabs sounds far better, but its free tier is 10k characters a month and
runs dry without warning. A mute assistant is useless, so when ElevenLabs
refuses (quota, bad key, no network) this falls back to the operating
system's own voice: worse sounding, but free, offline and unlimited —
macOS's built-in `say` on macOS, the SAPI synthesizer (via PowerShell, no
extra dependency needed) on Windows.
"""

import platform
import subprocess
import tempfile
from pathlib import Path

import requests

from . import config

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

MACOS_VOICE = "Anna"

IS_WINDOWS = platform.system() == "Windows"

# Set once ElevenLabs reports quota exhaustion, so we stop paying the
# latency of a doomed request on every single sentence.
_elevenlabs_blocked = False

# File extension + mime type produced by each engine, so callers (the /tts
# route, the filler cache) don't need their own platform checks.
ENGINE_MEDIA = {
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
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
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


def synthesize(text: str) -> bytes:
    """Return spoken audio for `text`. Never raises for ordinary failures —
    silence is the one outcome that makes Jarvis look broken."""
    global _elevenlabs_blocked

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
