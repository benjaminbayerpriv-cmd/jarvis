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

_lock = threading.Lock()
_pending: list[dict] = []


def push(kind: str, **fields) -> None:
    """Queue a panel item. `kind` is one of:
    image | code | markdown | files | link
    """
    with _lock:
        _pending.append({"kind": kind, **fields})


def drain() -> list[dict]:
    with _lock:
        items = list(_pending)
        _pending.clear()
    return items
