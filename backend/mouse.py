"""Cross-platform mouse control via pynput.

pynput drives the OS input stack directly on both platforms (Quartz on
macOS, the Win32 API on Windows), so click/move/drag/scroll all go through
one code path instead of separate macOS/Windows branches.

macOS still requires the process running this (Terminal, or python itself)
to be Accessibility-trusted (System Settings -> Privacy & Security ->
Accessibility), same as before — pynput's synthetic events are subject to
the same TCC check osascript/Quartz were. Windows needs no extra
permission for synthetic mouse input.
"""

import base64
import io
import re
import time

import requests
from PIL import Image
from pynput.mouse import Button, Controller

from . import config, panel, vision

_mouse = Controller()


def screen_size() -> tuple[int, int]:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return w, h
    except Exception:
        from PIL import ImageGrab

        return ImageGrab.grab().size


def move(x: float, y: float) -> None:
    _mouse.position = (int(x), int(y))


def click(x: float, y: float, button: str = "left", count: int = 1) -> None:
    x, y = int(x), int(y)
    _mouse.position = (x, y)
    btn = Button.right if button == "right" else Button.left
    _mouse.click(btn, max(count, 1))


def drag(x1: float, y1: float, x2: float, y2: float) -> None:
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    _mouse.position = (x1, y1)
    _mouse.press(Button.left)
    steps = 12
    for i in range(1, steps + 1):
        ix = x1 + (x2 - x1) * i / steps
        iy = y1 + (y2 - y1) * i / steps
        _mouse.position = (ix, iy)
        time.sleep(0.012)
    _mouse.release(Button.left)


def scroll(dx: int = 0, dy: int = 0) -> None:
    _mouse.scroll(dx, dy)


# ---------------------------------------------------------------------------
# Vision-grounded clicking

_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")


def click_on_screen(description: str, action: str = "click") -> str:
    """Screenshot, ask the vision model to point at `description`, click
    there. Reports back honestly — this is approximate, not pixel-exact."""
    try:
        shot_path = vision.capture_screen()
        raw = vision.downscale(shot_path, max_width=1400)
    except Exception as exc:
        return f"Konnte keinen Screenshot machen: {exc}"

    img = Image.open(io.BytesIO(raw))
    shot_w, shot_h = img.size
    real_w, real_h = screen_size()

    b64 = base64.b64encode(raw).decode("ascii")
    panel.push("image", title="Bildschirm", data_url=f"data:image/png;base64,{b64}")

    prompt = (
        f'Finde auf diesem Bild: "{description}". '
        f"Das Bild ist {shot_w}x{shot_h} Pixel groß. "
        "Antworte NUR mit den Pixel-Koordinaten der Mitte dieses Elements im Format "
        '"x,y". Keine Erklärung, kein anderer Text.'
    )
    try:
        resp = requests.post(
            f"{config.LM_STUDIO_BASE_URL}/chat/completions",
            json={
                "model": vision.VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                "max_tokens": 40,
                "reasoning_effort": "none",
            },
            timeout=180,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"].get("content", "").strip()
    except requests.RequestException as exc:
        return f"Bildanalyse fehlgeschlagen: {exc}"

    m = _COORD_RE.search(answer)
    if not m:
        return f"Konnte '{description}' nicht auf dem Bildschirm finden."

    ix, iy = float(m.group(1)), float(m.group(2))
    # Scale from the (possibly downscaled) screenshot back to real screen
    # pixels.
    x = ix * real_w / shot_w
    y = iy * real_h / shot_h

    if action == "double_click":
        click(x, y, count=2)
        return f"'{description}' doppelt angeklickt."
    if action == "right_click":
        click(x, y, button="right")
        return f"'{description}' rechtsgeklickt."
    if action == "move":
        move(x, y)
        return f"Zu '{description}' bewegt."

    click(x, y)
    return f"'{description}' angeklickt."
