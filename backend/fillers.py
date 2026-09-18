from pathlib import Path

from . import tts

FILLER_DIR = Path(__file__).resolve().parent.parent / "frontend" / "fillers"

PHRASES = [
    "Warte mal kurz.",
    "Moment, ich schau's mir an.",
    "Sekunde, bin dran.",
    "Kurz nachdenken.",
    "Gib mir 'nen Moment.",
    "Ich bin gleich so weit.",
    "Einen Augenblick.",
    "Lass mich kurz checken.",
    "Hmm, lass mich überlegen.",
    "Ich bin dran, kurz Geduld.",
    "Gib mir zwei Sekunden.",
    "Ich schau grad nach.",
    "Bin gleich fertig damit.",
    "Kurzer Moment noch.",
    "Ich denk kurz nach.",
    "Sekunde, ich klär das.",
    "Moment, das prüf ich eben.",
    "Bleib kurz dran.",
]


def ensure_fillers() -> list[str]:
    """Generate filler audio clips once and cache them on disk. Returns
    static URLs for whichever clips exist (already-cached ones are skipped,
    so this stays cheap after the first run)."""
    FILLER_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    for i, phrase in enumerate(PHRASES):
        # The extension depends on which engine produced the clip (wav for
        # Supertonic/Windows, mp3 for ElevenLabs, m4a on macOS's fallback),
        # so look for any cached file for this index regardless of extension.
        path = next(FILLER_DIR.glob(f"filler_{i}.*"), None)
        if path is None:
            try:
                audio = tts.synthesize(phrase)
                ext, _ = tts.ENGINE_MEDIA.get(tts.VoiceInfo.engine, ("mp3", "audio/mpeg"))
                path = FILLER_DIR / f"filler_{i}.{ext}"
                path.write_bytes(audio)
            except Exception:
                continue
        if path and path.exists():
            urls.append(f"/static/fillers/{path.name}")
    return urls


# Played mid-response in Sprachmodus when TTS catches up to the LLM — the
# audio queue empties but the model hasn't produced the next sentence yet.
# A short "Ähm" bridges that silence the way a person hesitates while still
# thinking, instead of dead air that sounds like the connection dropped.
# Separate from PHRASES/ensure_fillers() above (those are longer clips for
# a long *pre-reply* wait, e.g. a slow tool call) — this one is meant to be
# replayed repeatedly, in quick succession, mid-sentence.
THINKING_FILLER_STEM = "thinking_aehm"
THINKING_PHRASE = "Ähm"


def ensure_thinking_filler() -> str | None:
    """Generate (once, cached on disk like PHRASES above) the short
    mid-response filler clip. Returns its static URL, or None if synthesis
    failed (caller just won't have a filler to play, no different from
    Sprachmodus without this feature at all)."""
    FILLER_DIR.mkdir(parents=True, exist_ok=True)
    path = next(FILLER_DIR.glob(f"{THINKING_FILLER_STEM}.*"), None)
    if path is None:
        try:
            audio = tts.synthesize(THINKING_PHRASE)
            ext, _ = tts.ENGINE_MEDIA.get(tts.VoiceInfo.engine, ("mp3", "audio/mpeg"))
            path = FILLER_DIR / f"{THINKING_FILLER_STEM}.{ext}"
            path.write_bytes(audio)
        except Exception:
            return None
    return f"/static/fillers/{path.name}" if path and path.exists() else None
