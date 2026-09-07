"""Plain-text conversation transcript — a local debugging aid, not a
feature the app reads back. Replaces the old in-app debug/chat panel: that
UI doesn't fit a window sized for just a floating orb, so the same
turn-by-turn record now goes here instead, on disk, next to the code."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "transcript.log"
_lock = threading.Lock()


def log_turn(user_text: str, assistant_text: str) -> None:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] DU: {user_text}\n[{timestamp}] JARVIS: {assistant_text}\n\n"
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)


def log_panel_event(kind: str, fields: dict) -> None:
    """Everything that used to render in the removed chat/debug sidebar
    (tool-call status, build progress, background notifications, links,
    generated code) — there's no UI surface left for any of it now, so it
    comes here instead. Long values (a full generated file's text, a big
    shell output) are truncated so one event can't make the log unreadable."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = []
    for key, value in fields.items():
        text = str(value)
        if len(text) > 300:
            text = text[:300] + f"… ({len(text)} Zeichen gesamt)"
        parts.append(f"{key}={text!r}")
    entry = f"[{timestamp}] PANEL[{kind}] " + ", ".join(parts) + "\n"
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)
