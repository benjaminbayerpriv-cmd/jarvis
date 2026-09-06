"""Screen vision via a local multimodal model.

Takes a screenshot with Pillow's `ImageGrab`, which works natively on both
macOS and Windows, and asks gemma-4-e2b about it. Gemma is a reasoning
model like qwen3.5 — left to its own devices it spends its entire token
budget in reasoning_content and returns an empty answer, so reasoning is
switched off explicitly (verified: 7s and a correct German description
with it off, empty string with it on).
"""

import base64
import io
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageGrab

from . import config, panel

VISION_MODEL = "google/gemma-4-e2b"


def capture_screen() -> Path:
    path = Path(tempfile.gettempdir()) / "jarvis_screen.png"
    img = ImageGrab.grab()
    img.save(path, "PNG")
    return path


def downscale(path: Path, max_width: int = 1400) -> bytes:
    """Shrink so a high-DPI screenshot doesn't blow up the request (and the
    model's image budget)."""
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def look_at_screen(question: str = "") -> str:
    """Screenshot the display, show it in the panel, and answer `question`
    about it (or describe it if no question was given)."""
    try:
        shot = capture_screen()
    except Exception as exc:
        return f"Konnte keinen Screenshot machen: {exc}"

    raw = downscale(shot)
    b64 = base64.b64encode(raw).decode("ascii")

    panel.push("image", title="Bildschirm", data_url=f"data:image/png;base64,{b64}")

    prompt = question.strip() or "Beschreibe kurz, was auf diesem Bildschirm zu sehen ist."
    try:
        resp = requests.post(
            f"{config.LM_STUDIO_BASE_URL}/chat/completions",
            json={
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt + " Antworte auf Deutsch, kurz und konkret."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                "max_tokens": 400,
                # Without this gemma burns the whole budget on hidden
                # reasoning and returns "".
                "reasoning_effort": "none",
            },
            timeout=180,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"].get("content", "").strip()
        return answer or "Ich sehe den Bildschirm, kann ihn aber gerade nicht beschreiben."
    except requests.RequestException as exc:
        return f"Bildanalyse fehlgeschlagen: {exc}"
