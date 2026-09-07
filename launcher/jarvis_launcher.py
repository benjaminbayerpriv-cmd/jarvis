"""Double-clickable entry point for the packaged Jarvis app (macOS .app /
Windows .exe).

This is the app *is* the web interface: it starts the existing backend as
a background process, then opens a native window (via pywebview — a thin
wrapper around the OS's own WebKit/WebView2, not a browser tab) pointing
at it. Closing the window shuts the backend down with it.

Deliberately not a full PyInstaller freeze of the backend itself —
faster-whisper/ctranslate2 and Supertonic ship native compiled extensions
that are fragile to freeze correctly, and a broken freeze is much harder
to diagnose than a broken subprocess call. This just drives the existing,
already-working `.venv` the same way start_jarvis_windows.cmd /
start_server.bat do, with a real app window on top instead of a terminal.

The built app/exe must stay where the build script puts it
(launcher/dist/) — it locates the project by walking up from its own
location looking for backend/main.py, so moving it elsewhere (e.g.
dragging the .app to /Applications) breaks that lookup.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
URL = "http://127.0.0.1:8000"

# The floating widget's fixed size — no more expand/collapse case now that
# there's no debug/chat sidebar to grow into (see frontend/app.js and
# backend/transcript_log.py).
WIDGET_WIDTH = 340
WIDGET_HEIGHT = 430
# Always the same corner on launch — a floating widget with no title bar
# has no natural "restore position" affordance, so rather than trusting
# whatever the OS/backend defaults to (centered, or wherever it last was),
# it always starts somewhere predictable and easy to find.
SPAWN_X = 24
SPAWN_Y = 24


class Api:
    """Bridge for the one thing the page can't do to its own OS window:
    closing it. Exposed to JS as `window.pywebview.api.quit()` once
    pywebview injects it — see frontend/app.js."""

    window = None  # set right after create_window returns (see main())

    def quit(self) -> None:
        if self.window is not None:
            self.window.destroy()


def _find_root_dir() -> Path:
    # Checked both raw and symlink-resolved: a frozen app's own executable
    # is never a symlink, so resolving is harmless there, but testing this
    # script directly through a venv's `python3` (itself a symlink to the
    # real interpreter, often far outside the project) needs the raw path
    # instead — resolving it walks straight past the project entirely.
    raw = Path(getattr(sys, "executable", None) or sys.argv[0])
    starts = [raw]
    try:
        starts.append(raw.resolve())
    except OSError:
        pass
    for start in starts:
        for ancestor in (start, *start.parents):
            if (ancestor / "backend" / "main.py").exists():
                return ancestor
    raise RuntimeError("backend/main.py nicht gefunden")


def _fatal(message: str) -> None:
    if IS_WINDOWS:
        # ctypes needs no extra dependency and works even with the console
        # hidden (--windowed build) — a silent double-click failure would
        # otherwise look like the app does nothing at all.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Jarvis", 0x10)  # MB_ICONERROR
        except Exception:
            print(message)
    else:
        try:
            subprocess.run(
                ["osascript", "-e", f'display dialog "{message}" with title "Jarvis" buttons {{"OK"}} with icon stop'],
                timeout=30,
            )
        except Exception:
            print(message)
    sys.exit(1)


def _wait_until_up(timeout_s: float = 60) -> bool:
    # The server takes a few seconds to warm up (Whisper model load,
    # filler-clip generation) — poll instead of guessing a fixed delay.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            return True
        except Exception:
            time.sleep(1)
    return False


def main() -> None:
    try:
        root_dir = _find_root_dir()
    except RuntimeError:
        _fatal(
            "Konnte den Jarvis-Projektordner nicht finden.\n\n"
            "Diese App muss in launcher/dist/ bleiben, direkt neben dem "
            "restlichen Projekt — nicht an einen anderen Ort verschieben."
        )
        return

    venv_python = (
        root_dir / ".venv" / "Scripts" / "python.exe"
        if IS_WINDOWS
        else root_dir / ".venv" / "bin" / "python3"
    )
    if not venv_python.exists():
        _fatal(
            "Jarvis wurde noch nicht eingerichtet.\n\n"
            "Bitte einmal SETUP.md folgen (venv anlegen, "
            "pip install -r requirements.txt), dann diese App erneut starten."
        )
        return

    # Redirected to a real file instead of left on the default (for a
    # --windowed/no-console build, effectively nowhere) — the "not
    # reachable after 60 seconds" message below already told people to
    # check this file even before it actually existed. Written next to the
    # actual project (root_dir), not next to the frozen executable itself —
    # __file__ inside a PyInstaller build points into a temporary
    # extraction directory, not anywhere a user could go looking.
    server_log_path = root_dir / "launcher" / "server.err.log"
    server_log = open(server_log_path, "w")
    server = subprocess.Popen(
        [str(venv_python), "-m", "backend.main"],
        cwd=str(root_dir),
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )

    try:
        if not _wait_until_up():
            _fatal(
                "Jarvis-Server ist nach 60 Sekunden nicht erreichbar geworden.\n"
                "Details stehen im Terminal-Log bzw. in launcher/server.err.log."
            )
            return

        # Imported only once the server's up — pywebview's own window-system
        # init is the slow/fragile part, no reason to pay for it if the
        # server never came up in the first place.
        import webview

        api = Api()
        # frameless + transparent + on_top turns the window into a floating
        # widget: just the orb and its two small controls hovering over the
        # desktop instead of an opaque app window covering the screen.
        # easy_drag makes the borderless window still moveable by dragging
        # its background/orb (pywebview skips this for actual buttons on
        # its own). Not resizable — a fixed-size widget has no use for
        # resize handles, and (transparent windows already force
        # setHasShadow_(False) on macOS regardless of a `shadow` kwarg)
        # there's nothing left for that flag to do here.
        window = webview.create_window(
            "Jarvis",
            URL,
            width=WIDGET_WIDTH,
            height=WIDGET_HEIGHT,
            x=SPAWN_X,
            y=SPAWN_Y,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=True,
            resizable=False,
            js_api=api,
        )
        api.window = window
        # Windows only: forces pywebview's Qt backend (PyQt6 + QtWebEngine,
        # installed via `pip install pywebview[qt6]`) instead of letting it
        # default to edgechromium/WinForms. WinForms' transparent=True only
        # makes the WebView2 *control's* background see-through, never the
        # containing Form itself — real desktop transparency needs
        # Form.AllowTransparency, which that backend never sets (confirmed
        # by reading webview/platforms/winforms.py directly). Patching that
        # in was tried and reverted: it does make the window transparent,
        # but also breaks Windows' accessibility Bounds lookup on the Form
        # ("maximum recursion depth exceeded", observed live). Qt's own
        # QWidget.setAttribute(Qt.WA_TranslucentBackground) — what
        # webview/platforms/qt.py actually uses — is the standard,
        # well-tested mechanism real transparent Qt windows use; no patching
        # needed. macOS already gets proper transparency from the cocoa
        # backend, so this is Windows-only.
        webview.start(gui="qt" if IS_WINDOWS else None)
    finally:
        # The window closing is the signal to shut everything down — a
        # server left running invisibly in the background, un-killable
        # without a terminal, would be a worse failure mode than the app
        # not appearing at all.
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
