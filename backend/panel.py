"""Rich content channel.

Tools run synchronously deep inside the LLM loop, but some of them produce
things that belong on screen rather than in Jarvis's spoken reply — a
screenshot, a file listing, generated code, a table. Those get pushed here;
the streaming endpoint drains the queue after each tool round and forwards
the items to the browser, which renders them in the canvas panel.

This keeps the voice channel short ("hab ich dir angezeigt") while the
actual content lands somewhere you can read it.
"""

import threading

from . import discord_bot, transcript_log

_lock = threading.Lock()
_pending: list[dict] = []


def push(kind: str, **fields) -> None:
    """Queue a panel item. `kind` is one of:
    image | code | markdown | files | link | task | notify | action

    Also written to backend/transcript.log — the packaged app's window is
    now just a floating orb with no room for a chat/debug sidebar, so this
    is the only place any of it (tool status, build progress, background
    notifications) still ends up.

    "notify" items additionally go out as a Discord DM (backend/discord_bot.py)
    if configured — Jarvis pinging you when a background task is done."""
    with _lock:
        _pending.append({"kind": kind, **fields})
    transcript_log.log_panel_event(kind, fields)
    if kind == "notify" and fields.get("text"):
        discord_bot.notify(fields["text"])


def drain() -> list[dict]:
    with _lock:
        items = list(_pending)
        _pending.clear()
    return items
