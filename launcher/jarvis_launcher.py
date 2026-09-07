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

# A normal, opaque app window — its own title bar (with the OS's native
# close/minimize controls) is how you close it, no custom frameless/
# transparent/always-on-top widget behaviour.
WINDOW_WIDTH = 480
WINDOW_HEIGHT = 640


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

        webview.create_window(
            "Jarvis",
            URL,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(360, 480),
        )
        webview.start()
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
