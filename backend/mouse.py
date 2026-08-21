"""Mouse control on macOS and Windows.

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

from __future__ import annotations

import base64
import io
import re
import subprocess
import time
from collections import Counter

import requests
from PIL import Image
from pynput import mouse as pynput_mouse

from . import config, panel, platform_utils, vision

if platform_utils.is_macos():
    import Quartz
else:
    Quartz = None


def screen_size() -> tuple[int, int]:
    if platform_utils.is_macos():
        bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return int(bounds.size.width), int(bounds.size.height)
    if platform_utils.is_windows():
        import ctypes

        return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    with Image.open(vision.capture_screen()) as shot:
        return shot.size


def _osascript(script: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        # System Events can briefly hang (permission prompt, busy app). Report
        # failure rather than letting the exception crash the whole tool round.
        return None


def _move_mouse(x: int, y: int) -> None:
    """Move the cursor visibly (best-effort).

    `osascript`'s `click at` clicks without moving the on-screen cursor, so a
    click looks like nothing happened. pynput's `Controller.position` uses
    CGWarpMouseCursorPosition, which moves the cursor without needing the
    Accessibility trust that CGEventPost (and therefore a real synthetic click)
    requires — so the move is visible even when the click path has to go
    through osascript. When it fails, the osascript click still lands.
    """
    try:
        pynput_mouse.Controller().position = (int(x), int(y))
    except Exception:
        pass


def click(x: float, y: float, button: str = "left", count: int = 1) -> bool:
    """Click at screen coordinates; returns True if the click was dispatched."""
    x, y = int(x), int(y)
    if not platform_utils.is_macos():
        controller = pynput_mouse.Controller()
        controller.position = (x, y)
        controller.click(pynput_mouse.Button.right if button == "right" else pynput_mouse.Button.left, count)
        return True

    # Move the cursor visibly first, then click via osascript (the reliable,
    # Apple-signed path that already holds Accessibility trust).
    _move_mouse(x, y)
    time.sleep(0.05)

    if button == "right":
        script = f'''
        tell application "System Events"
            key down control
            click at {{{x}, {y}}}
            key up control
        end tell'''
        proc = _osascript(script)
        return proc is not None and proc.returncode == 0

    clicks = "\n            delay 0.05\n            ".join([f"click at {{{x}, {y}}}"] * max(count, 1))
    proc = _osascript(f'tell application "System Events"\n            {clicks}\n        end tell')
    return proc is not None and proc.returncode == 0


def drag(x1: float, y1: float, x2: float, y2: float) -> None:
    """Best-effort — osascript has no drag primitive, so this needs the
    Quartz path to be trusted (see module docstring). No-ops silently if not."""
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    if not platform_utils.is_macos():
        controller = pynput_mouse.Controller()
        controller.position = (x1, y1)
        controller.press(pynput_mouse.Button.left)
        controller.position = (x2, y2)
        controller.release(pynput_mouse.Button.left)
        return
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
    if not platform_utils.is_macos():
        pynput_mouse.Controller().scroll(int(dx), int(dy))
        return
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, int(dy), int(dx))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


# ---------------------------------------------------------------------------
# Vision-grounded clicking

_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")


def _ask_vision(prompt: str, png_bytes: bytes) -> str | None:
    """One vision request against the active backend (Gemini or LM Studio);
    returns the raw text answer, or None on failure."""
    try:
        return vision._ask_vision_model(prompt, png_bytes)
    except Exception:
        return None


def find_on_screen(description: str) -> tuple[float, float] | None:
    """Locate an element by asking the vision model to pick a grid cell.

    Small multimodal models (gemma-4-e4b) are unreliable at naming absolute
    pixel coordinates — three runs on the same screenshot scatter hundreds of
    pixels. A discrete "pick the grid cell" task is something they do far more
    consistently, so this divides the screenshot into a grid, asks several
    times, and takes the majority cell. Still approximate, but it no longer
    teleports the click to a random corner of the screen.
    """
    try:
        shot_path = vision.capture_screen()
        raw = vision.downscale(shot_path, max_width=1400)
    except Exception:
        return None

    img = Image.open(io.BytesIO(raw))
    shot_w, shot_h = img.size
    real_w, real_h = screen_size()

    b64 = base64.b64encode(raw).decode("ascii")
    panel.push("image", title="Bildschirm", data_url=f"data:image/png;base64,{b64}")

    # Grid sized to the 2.4:1 aspect ratio; ~96 cells keeps each cell small
    # enough to be useful but still recognisable to the model.
    cols, rows = 16, 6
    prompt = (
        f'Dieses Bild ist in ein Raster von {cols} Spalten (0 bis {cols - 1}, links nach rechts) '
        f'und {rows} Zeilen (0 bis {rows - 1}, oben nach unten) aufgeteilt. '
        f'In welcher Zelle befindet sich "{description}"? '
        f'Antworte NUR mit "spalte,zeile", zum Beispiel "7,3".'
    )

    # A single request, not three: the free-tier vision quota is only 20
    # requests/minute per model (measured directly against a real 429), and
    # a multi-turn screen-control conversation burns through that fast. The
    # majority-vote scaffolding stays in place — Gemini is precise enough in
    # one shot to make this safe, but bumping the range back up costs only a
    # number if that ever stops being true.
    cells: list[tuple[int, int]] = []
    for _ in range(1):
        answer = _ask_vision(prompt, raw)
        if not answer:
            continue
        m = re.search(r"(\d+)\s*[,;]\s*(\d+)", answer)
        if not m:
            continue
        col, row = int(m.group(1)), int(m.group(2))
        if 0 <= col < cols and 0 <= row < rows:
            cells.append((col, row))

    if not cells:
        return None

    # Majority cell, else the median — both are robust against the one-off
    # wild guess the model sometimes throws in.
    ((col, row), count), = Counter(cells).most_common(1)
    if count < 2:
        col = sorted(c[0] for c in cells)[len(cells) // 2]
        row = sorted(c[1] for c in cells)[len(cells) // 2]

    # Cell centre in the downscaled image, then scaled back to real pixels.
    ix = (col + 0.5) * shot_w / cols
    iy = (row + 0.5) * shot_h / rows
    x = ix * real_w / shot_w
    y = iy * real_h / shot_h
    return (x, y)


def click_on_screen(description: str, action: str = "click") -> str:
    """Screenshot, ask the vision model to point at `description`, click
    there. Reports back honestly — this is approximate, not pixel-exact."""
    coords = find_on_screen(description)
    if coords is None:
        return f"Konnte '{description}' nicht auf dem Bildschirm finden."

    x, y = coords

    if action == "double_click":
        ok = click(x, y, count=2)
        return f"'{description}' doppelt angeklickt bei ({int(x)}, {int(y)})." if ok else f"Klick fehlgeschlagen: System Events konnte bei ({int(x)}, {int(y)}) nicht klicken."
    if action == "right_click":
        ok = click(x, y, button="right")
        return f"'{description}' rechtsgeklickt bei ({int(x)}, {int(y)})." if ok else f"Klick fehlgeschlagen: System Events konnte bei ({int(x)}, {int(y)}) nicht klicken."
    if action == "move":
        # Genuine hover, no click: _move_mouse uses CGWarpMouseCursorPosition
        # (see its docstring), which repositions the cursor without needing
        # the Accessibility trust a real click does.
        _move_mouse(x, y)
        return f"Maus zu '{description}' bewegt ({int(x)}, {int(y)})."

    ok = click(x, y)
    return f"'{description}' angeklickt bei ({int(x)}, {int(y)})." if ok else f"Klick fehlgeschlagen: System Events konnte bei ({int(x)}, {int(y)}) nicht klicken."
