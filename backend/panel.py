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

from . import transcript_log

_lock = threading.Lock()
_pending: list[dict] = []
_last_notice: str | None = None


def push(kind: str, **fields) -> None:
    """Queue a panel item. `kind` is one of:
    image | code | markdown | files | link | task | notice | action

    Also written to backend/transcript.log — the packaged app's window is
    now just a floating orb with no room for a chat/debug sidebar, so this
    is the only place any of it (tool status, build progress, background
    notifications) still ends up."""
    global _last_notice
    with _lock:
        _pending.append({"kind": kind, **fields})
        if kind in ("notice", "notify") and fields.get("text"):
            _last_notice = fields["text"]
    transcript_log.log_panel_event(kind, fields)


def last_notice() -> str | None:
    """The most recent status/notice text — survives the queue drain, so a
    page that connects later can still render it (model detail on startup
    is broadcast before the browser even opens)."""
    with _lock:
        return _last_notice


def drain() -> list[dict]:
    with _lock:
        items = list(_pending)
        _pending.clear()
    return items
