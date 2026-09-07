"""Speech-to-text via a local Whisper model (faster-whisper).

Replaces the browser's Web Speech API for German recognition, which was
unreliable enough to be a running complaint. Runs fully offline like
Supertonic TTS — the browser records audio locally and posts it here;
transcription never leaves the machine.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
from pathlib import Path


def _add_nvidia_dll_dirs() -> None:
    """Make the cuBLAS/cuDNN DLLs from the `nvidia-*-cu12` pip packages
    loadable on Windows.

    Those packages ship the DLLs under site-packages/nvidia/<name>/bin, but
    pip install alone doesn't put that anywhere ctranslate2 can find it.
    os.add_dll_directory() looks like the right fix and silently does
    *nothing* here: it only affects LoadLibraryEx calls made with the
    LOAD_LIBRARY_SEARCH_* flags, and ctranslate2's C++ core loads cuBLAS/
    cuDNN via a plain LoadLibrary, which only ever consults PATH (plus the
    classic system/application directories) — confirmed by reproducing the
    failure with add_dll_directory in place and fixing it only once these
    same folders were prepended to PATH instead. Without this, GPU
    transcription loads fine but the first real (non-silence) utterance
    fails with "Library cublas64_12.dll is not found or cannot be loaded",
    and that failure is swallowed by main.py's /stt handler into an empty
    transcript — heard by the user as "voice input doesn't work".
    """
    if os.name != "nt":
        return
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return
    bin_dirs = [str(p) for p in nvidia_root.glob("*/bin")]
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402

from . import config  # noqa: E402

_lock = threading.Lock()
_model: WhisperModel | None = None

# Whisper is trained on huge amounts of YouTube-style audio and reliably
# hallucinates one of its stock sign-off phrases when fed silence or faint
# background noise instead of real speech — a well-known artifact of the
# model itself, not something specific to this setup. Jarvis records
# continuously while listening, so quiet stretches reach the model far more
# often than in a push-to-talk app, making this show up constantly ("Vielen
# Dank fürs Zuschauen" appearing on its own after a while of silence).
#
# The real fix is the confidence filter below (no_speech_prob), which
# catches this class of hallucination regardless of which stock phrase it
# picks — this list is just a backstop for the handful of exact phrases
# common enough to be worth a direct, zero-cost check first.
_HALLUCINATION_PHRASES = {
    "vielen dank fürs zuschauen",
    "vielen dank für's zuschauen",
    "vielen dank fürs zuhören",
    "vielen dank für's zuhören",
    "danke fürs zuschauen",
    "danke fürs zuhören",
    "untertitelung aufgrund der amara.org-community",
    "untertitel im auftrag des zdf",
    "das video wurde von der amara.org-community untertitelt",
    "bis zum nächsten mal",
    "wir sehen uns im nächsten video",
    "abonniert den kanal",
}

# Segments Whisper itself flags as more likely silence than speech
# (no_speech_prob) are exactly where the hallucinated sign-offs come from —
# dropping them is a general defense against the whole class of "invented
# stock phrase" hallucination, not just the specific ones listed above.
_NO_SPEECH_THRESHOLD = 0.6


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    # float16 on GPU: several times faster than CPU int8,
                    # and this model is reloaded only once per process, so
                    # the one-time GPU init cost is irrelevant afterwards.
                    _model = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16")
                except Exception as exc:
                    print(f"[stt] CUDA nicht verfügbar, falle auf CPU zurück: {exc}")
                    _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe a short recorded utterance (WAV, built client-side from
    raw PCM — see frontend/app.js for why not WebM/MediaRecorder).

    Serialized through the same lock as model loading — like Supertonic in
    backend/tts.py, whether one CTranslate2 model tolerates concurrent
    calls from different threads is undocumented, and a browser sends one
    utterance at a time anyway.
    """
    model = _get_model()
    # delete=False + a manual close before transcribe: on Windows, a file
    # opened via NamedTemporaryFile is held exclusively, so passing its name
    # to model.transcribe() while the handle is still open fails with
    # PermissionError (WinError 13) — reproducible every time, invisible on
    # macOS/Linux since those allow a second open on an already-open file.
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        with _lock:
            segments, _info = model.transcribe(
                path,
                language="de",
                vad_filter=True,
                # A hallucinated segment tends to seed the next one with the
                # same invented text otherwise — this stops each segment
                # from being conditioned on a previous hallucination.
                condition_on_previous_text=False,
            )
            kept = [seg.text.strip() for seg in segments if seg.no_speech_prob < _NO_SPEECH_THRESHOLD]
        text = " ".join(kept).strip()
    finally:
        os.remove(path)

    normalized = re.sub(r"[.!?]+$", "", text.strip().lower())
    if normalized in _HALLUCINATION_PHRASES:
        return ""
    return text
