"""Double-clickable entry point for the packaged Jarvis .exe.

This is deliberately a thin launcher, not a full PyInstaller freeze of the
backend itself: faster-whisper/ctranslate2 and Supertonic ship native
compiled extensions that are fragile to freeze correctly, and a broken
freeze is much harder to diagnose than a broken subprocess call. Instead,
this .exe just drives the existing, already-working `.venv` the same way
start_jarvis_windows.cmd does — it only adds the "double-click an app icon"
experience: hidden console, an early error dialog instead of a silent
crash, and the browser opening on its own once the server is up.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(sys.argv[0]).resolve().parent.parent
VENV_PYTHON = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
URL = "http://127.0.0.1:8000"


def _fatal(message: str) -> None:
    # ctypes MessageBoxW needs no extra dependency and works even when the
    # console is hidden (--windowed build) — a silent double-click failure
    # would otherwise look like the app does nothing at all.
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "Jarvis", 0x10)  # MB_ICONERROR
    except Exception:
        print(message)
    sys.exit(1)


def _wait_and_open_browser() -> None:
    # The server takes a few seconds to warm up (Whisper model load,
    # filler-clip generation) — poll instead of guessing a fixed delay.
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            webbrowser.open(URL)
            return
        except Exception:
            time.sleep(1)


def main() -> None:
    if not VENV_PYTHON.exists():
        _fatal(
            "Jarvis wurde noch nicht eingerichtet.\n\n"
            "Bitte einmal SETUP.md folgen (venv anlegen, "
            "pip install -r requirements.txt), dann diese App erneut starten."
        )

    threading.Thread(target=_wait_and_open_browser, daemon=True).start()

    proc = subprocess.run([str(VENV_PYTHON), "-m", "backend.main"], cwd=str(ROOT_DIR))
    if proc.returncode != 0:
        _fatal(
            f"Jarvis wurde mit Fehlercode {proc.returncode} beendet.\n"
            "Details stehen im Terminal-Log bzw. in launcher/server.err.log."
        )


if __name__ == "__main__":
    main()
