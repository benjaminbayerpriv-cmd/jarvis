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
