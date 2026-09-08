"""Plain-text conversation transcript — a local debugging aid, not a
feature the app reads back. Replaces the old in-app debug/chat panel: that
UI doesn't fit a window sized for just a floating orb, so the same
turn-by-turn record now goes here instead, on disk, next to the code."""

from __future__ import annotations

import datetime as dt
import re
import threading
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "transcript.log"
_lock = threading.Lock()


def log_turn(user_text: str, assistant_text: str, mode: str = "chat") -> None:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode_tag = f"[{mode}]" if mode else ""
    entry = f"[{timestamp}]{mode_tag} DU: {user_text}\n[{timestamp}]{mode_tag} JARVIS: {assistant_text}\n\n"
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)


# Optionaler [mode]-Tag zwischen Zeitstempel und Rolle: [ts][code] DU: ... — alte
# Zeilen ohne Tag werden als "chat" gelesen.
_TURN_RE = re.compile(r"^\[[^\]]+\](?:\[([a-z]+)\])? (DU|JARVIS): (.*)$")


def read_recent_turns(limit: int = 40) -> list[dict]:
    """The last `limit` DU/JARVIS lines, oldest first, for the chat panel's
    scroll-back on open — PANEL[...] lines (tool calls, background
    notifications) are internal debugging noise, not part of the
    conversation, so they're skipped here rather than shown as turns."""
    if not LOG_FILE.exists():
        return []
    with _lock:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    turns = []
    for line in lines:
        m = _TURN_RE.match(line)
        if m:
            mode, role, text = m.group(1) or "chat", m.group(2), m.group(3)
            turns.append({"role": "you" if role == "DU" else "jarvis", "text": text, "mode": mode})
    return turns[-limit:]


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
