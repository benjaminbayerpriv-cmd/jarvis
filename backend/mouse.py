"""Mouse control on macOS.

The obvious approach is Quartz CGEvent — direct HID-level synthetic input,
same mechanism macOS itself uses. It needs the calling process to be
Accessibility-trusted, though, and Homebrew's Python.app is only ad-hoc
signed (no Team ID, a hash-based identity). In practice that made TCC's
grant unreliable here: the toggle in System Settings showed on, but
AXIsProcessTrusted() kept coming back false — the registered entry never
matched the running binary's identity.

`osascript` (System Events) doesn't have that problem — it's a stable,
Apple-signed binary, and Terminal.app already carried Accessibility trust
that flows through to it. `click at {x,y}` is a private but working System
Events verb; that's the one avenue confirmed to actually move a real click
here, so it's the primary path for anything that matters (an actual click).
Quartz stays in for scrolling and drag, which osascript has no equivalent
for — those work once/if the Python binary itself gets trusted, and no-op
harmlessly otherwise.
"""

import base64
import io
import re
import subprocess
import time

import Quartz
import requests
from PIL import Image

from . import config, panel, vision


def screen_size() -> tuple[int, int]:
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return int(bounds.size.width), int(bounds.size.height)


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)


def click(x: float, y: float, button: str = "left", count: int = 1) -> None:
    x, y = int(x), int(y)
    if button == "right":
        script = f'''
        tell application "System Events"
            key down control
            click at {{{x}, {y}}}
            key up control
        end tell'''
        _osascript(script)
        return

    clicks = "\n            delay 0.05\n            ".join([f"click at {{{x}, {y}}}"] * max(count, 1))
    _osascript(f'tell application "System Events"\n            {clicks}\n        end tell')


def drag(x1: float, y1: float, x2: float, y2: float) -> None:
    """Best-effort — osascript has no drag primitive, so this needs the
    Quartz path to be trusted (see module docstring). No-ops silently if not."""
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    move = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x1, y1), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
    time.sleep(0.05)
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, (x1, y1), Quartz.kCGMouseButtonLeft),
    )
    steps = 12
    for i in range(1, steps + 1):
        ix = x1 + (x2 - x1) * i / steps
        iy = y1 + (y2 - y1) * i / steps
        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDragged, (ix, iy), Quartz.kCGMouseButtonLeft),
        )
        time.sleep(0.012)
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, (x2, y2), Quartz.kCGMouseButtonLeft),
    )


def scroll(dx: int = 0, dy: int = 0) -> None:
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, int(dy), int(dx))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


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
        # No pure-hover primitive via osascript; approximate with a click.
        click(x, y)
        return f"Bei '{description}' geklickt (reines Bewegen ohne Klick wird gerade nicht unterstützt)."

    click(x, y)
    return f"'{description}' angeklickt."
