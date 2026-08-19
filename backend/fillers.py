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
        path = FILLER_DIR / f"filler_{i}.mp3"
        if not path.exists():
            try:
                audio = tts.synthesize(phrase)
                path.write_bytes(audio)
            except Exception:
                continue
        if path.exists():
            urls.append(f"/static/fillers/{path.name}")
    return urls
