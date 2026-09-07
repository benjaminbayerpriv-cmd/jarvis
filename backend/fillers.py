from pathlib import Path

from . import tts

FILLER_DIR = Path(__file__).resolve().parent.parent / "frontend" / "fillers"

# Extension must match the actual container the engine returns — the
# browser's <audio> element trusts the file extension, and a WAV clip
# saved as ".mp3" fails to play in some browsers.
_ENGINE_EXT = {"macos": "m4a", "windows": "wav", "supertonic": "wav"}

PHRASES = [
    "Warte mal kurz.",
    "Moment, ich schau's mir an.",
    "Sekunde, bin dran.",
    "Kurz nachdenken.",
    "Gib mir 'nen Moment.",
    "Ich bin gleich so weit.",
    "Einen Augenblick.",
    "Lass mich kurz checken.",
]


def ensure_fillers() -> list[str]:
    """Generate filler audio clips once and cache them on disk. Returns
    static URLs for whichever clips exist (already-cached ones are skipped,
    so this stays cheap after the first run)."""
    FILLER_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    for i, phrase in enumerate(PHRASES):
        existing = next(FILLER_DIR.glob(f"filler_{i}.*"), None)
        if existing is None:
            try:
                audio = tts.synthesize(phrase)
            except Exception:
                continue
            ext = _ENGINE_EXT.get(tts.VoiceInfo.engine, "mp3")
            existing = FILLER_DIR / f"filler_{i}.{ext}"
            existing.write_bytes(audio)
        urls.append(f"/static/fillers/{existing.name}")
    return urls
