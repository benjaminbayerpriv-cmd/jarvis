"""Screen vision via a local multimodal model.

Takes a screenshot with macOS's `screencapture` and asks gemma-4-e2b about
it. Gemma is a reasoning model like qwen3.5 — left to its own devices it
spends its entire token budget in reasoning_content and returns an empty
answer, so reasoning is switched off explicitly (verified: 7s and a correct
German description with it off, empty string with it on).
"""

import base64
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageGrab

from . import config, panel, platform_utils

VISION_MODEL = "google/gemma-4-e2b"


def capture_screen() -> Path:
    path = Path(tempfile.gettempdir()) / "jarvis_screen.png"
    _capture_to(path)
    return path


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _capture_to(path: Path) -> None:
    """Save the primary display without importing macOS-only libraries."""
    if platform_utils.is_macos():
        subprocess.run(["screencapture", "-x", str(path)], check=True, timeout=20)
        return
    if platform_utils.is_windows():
        target = _powershell_quote(str(path))
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
            f"$bmp.Save({target},[System.Drawing.Imaging.ImageFormat]::Png); "
            "$g.Dispose(); $bmp.Dispose()"
        )
        subprocess.run(platform_utils.powershell(script), check=True, timeout=20)
        return
    ImageGrab.grab().save(path, "PNG")


def save_screenshot(location: str = "") -> str:
    """Capture the screen and keep it as a real file the user can open.

    `look_at_screen` also screenshots, but only to feed the vision model —
    the image lives in a temp dir and is effectively gone. Asking Jarvis to
    "save a screenshot to the Desktop" is a different job, and without a
    tool for it the model simply invented one and claimed success.
    """
    import datetime

    target = (location or "").strip().strip("\"'")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d um %H.%M.%S")
    filename = f"Bildschirmfoto {stamp}.png"

    if not target:
        dest = Path.home() / "Desktop" / filename
    else:
        p = Path(os.path.expanduser(target))
        if not p.is_absolute():
            # "Desktop/foo" must not become ~/Desktop/Desktop/foo
            head = p.parts[0] if p.parts else ""
            if head and (Path.home() / head).is_dir():
                p = Path.home() / p
            else:
                p = Path.home() / "Desktop" / p
        dest = p / filename if (p.is_dir() or not p.suffix) else p

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Two shots in the same second would otherwise silently overwrite.
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = dest.with_name(f"{stem} ({n}){suffix}")
            n += 1
    try:
        _capture_to(dest)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return f"Screenshot fehlgeschlagen: {exc}"

    if not dest.exists() or dest.stat().st_size == 0:
        return "Screenshot fehlgeschlagen, die Datei wurde nicht angelegt."

    try:
        b64 = base64.b64encode(downscale(dest, 900)).decode("ascii")
        panel.push("image", title=dest.name, data_url=f"data:image/png;base64,{b64}")
    except Exception:
        pass

    return f"Screenshot gespeichert unter {dest}."


def downscale(path: Path, max_width: int = 1400) -> bytes:
    """Shrink screenshots with Pillow; works on macOS and Windows alike."""
    import io

    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue()


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
