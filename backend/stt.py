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


# Once a real GPU failure is seen (as opposed to WhisperModel(cuda) simply
# never having been asked to compute anything yet — model construction
# alone doesn't touch cuBLAS/cuDNN), every later call goes straight to CPU
# instead of re-attempting and failing GPU init each time. Model
# construction succeeding is not proof the GPU path actually works: that
# was exactly how the cublas64_12.dll bug hid behind a silent-looking
# "success" for a VAD-filtered silent clip, only surfacing on real speech.
_gpu_broken = False


def _build_model(device: str) -> WhisperModel:
    compute_type = "float16" if device == "cuda" else "int8"
    return WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute_type)


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                if _gpu_broken:
                    _model = _build_model("cpu")
                else:
                    try:
                        # float16 on GPU: several times faster than CPU
                        # int8, and this model is reloaded only once per
                        # process, so the one-time GPU init cost is
                        # irrelevant afterwards.
                        _model = _build_model("cuda")
                    except Exception as exc:
                        print(f"[stt] CUDA nicht verfügbar, falle auf CPU zurück: {exc}")
                        _model = _build_model("cpu")
    return _model


def _run_transcribe(model: WhisperModel, path: str) -> str:
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
    return " ".join(kept).strip()


def selftest() -> None:
    """Actually exercise the GPU compute path at startup instead of only
    constructing the model (see the on_startup warmup call in main.py).

    Model construction alone never touches cuBLAS/cuDNN — that only happens
    once real encoder/decoder math runs — so it can't catch a broken GPU
    setup. A plain silent/tone clip can't either, since vad_filter=True
    (the default used everywhere else) strips it before it ever reaches the
    model, letting a real bug (the cublas64_12.dll case) hide until the
    first genuine spoken utterance. Random noise with vad_filter=False
    forces the real computation to run, so a failure here — and the
    automatic CPU fallback below — happens at boot, in the log, instead of
    silently on the user's first sentence.
    """
    import numpy as np

    model = _get_model()
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            import wave

            rng = np.random.default_rng(0)
            samples = (rng.standard_normal(16000) * 3000).astype("int16")
            with wave.open(f, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(samples.tobytes())
        with _lock:
            list(model.transcribe(path, language="de", vad_filter=False)[0])
        print(f"[stt] Selbsttest ok ({model.model.device}).")
    except Exception as exc:
        global _model, _gpu_broken
        print(f"[stt] Selbsttest fehlgeschlagen, wechsle dauerhaft auf CPU: {exc}")
        _gpu_broken = True
        with _lock:
            _model = _build_model("cpu")
    finally:
        os.remove(path)


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe a short recorded utterance (WAV, built client-side from
    raw PCM — see frontend/app.js for why not WebM/MediaRecorder).

    Serialized through the same lock as model loading — like Supertonic in
    backend/tts.py, whether one CTranslate2 model tolerates concurrent
    calls from different threads is undocumented, and a browser sends one
    utterance at a time anyway.
    """
    global _model, _gpu_broken

    # delete=False + a manual close before transcribe: on Windows, a file
    # opened via NamedTemporaryFile is held exclusively, so passing its name
    # to model.transcribe() while the handle is still open fails with
    # PermissionError (WinError 13) — reproducible every time, invisible on
    # macOS/Linux since those allow a second open on an already-open file.
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        model = _get_model()
        try:
            with _lock:
                text = _run_transcribe(model, path)
        except Exception as exc:
            # A GPU failure here (driver hiccup, VRAM pressure from
            # whatever else is running, a missing DLL that only breaks on
            # this particular batch shape) used to just vanish into an
            # empty transcript with a log line nobody was watching — heard
            # by the user as "voice input doesn't work". Recover instead:
            # fall back to CPU permanently and actually finish this
            # utterance rather than dropping it.
            if _gpu_broken:
                raise
            print(f"[stt] GPU-Transkription fehlgeschlagen, wechsle dauerhaft auf CPU: {exc}")
            _gpu_broken = True
            with _lock:
                _model = _build_model("cpu")
                text = _run_transcribe(_model, path)
    finally:
        os.remove(path)

    normalized = re.sub(r"[.!?]+$", "", text.strip().lower())
    if normalized in _HALLUCINATION_PHRASES:
        return ""
    return text
