"""Per-conversation chat history for the sidebar's conversation list.

Replaces the single, endless transcript.log as the thing the chat panel
reads back: each conversation gets its own JSON file with a short
auto-generated title (see llm_client.generate_title), so the panel can
list past conversations Claude-sidebar-style instead of one continuous
scroll-back with no boundaries.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from pathlib import Path

DIR = Path(__file__).resolve().parent / "conversations"
_lock = threading.Lock()


def new_id() -> str:
    return str(uuid.uuid4())


def _path(conv_id: str) -> Path:
    # conv_id normally comes from crypto.randomUUID() on the frontend (or
    # new_id() above) — never from arbitrary user text — but is still
    # sanitized defensively so a malformed id can't escape DIR.
    safe = "".join(c for c in conv_id if c.isalnum() or c in "-_") or "conversation"
    return DIR / f"{safe}.json"


def _load(conv_id: str) -> dict | None:
    path = _path(conv_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save(conv: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    _path(conv["id"]).write_text(
        json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_turns(conv_id: str) -> list[dict]:
    conv = _load(conv_id)
    return conv["turns"] if conv else []


def append_turn(conv_id: str, user_text: str, assistant_text: str, project_id: str | None = None) -> dict:
    """Appends one turn, creating the conversation file on first use.

    Returns the full conversation dict so the caller can tell whether a
    title still needs generating — it stays None until the first exchange
    has actually happened. ``project_id`` only takes effect the moment the
    conversation is first created; later turns just carry whatever the
    frontend already knows and can't change which project a conversation
    belongs to.
    """
    with _lock:
        conv = _load(conv_id)
        now = dt.datetime.now().isoformat(timespec="seconds")
        if conv is None:
            conv = {"id": conv_id, "title": None, "created_at": now, "turns": [], "project_id": project_id}
        conv["turns"].append({"role": "you", "text": user_text})
        conv["turns"].append({"role": "jarvis", "text": assistant_text})
        conv["updated_at"] = now
        _save(conv)
        return conv


def set_title(conv_id: str, title: str) -> None:
    with _lock:
        conv = _load(conv_id)
        if conv is None:
            return
        conv["title"] = title
        _save(conv)


def list_conversations(project_id: str | None = None) -> list[dict]:
    """Metadata only (id/title/updated_at), newest first — the sidebar
    never needs the full turn list just to render its entries. Pass
    project_id to get only conversations started from that project's page
    (see backend/projects.py) — used by the project detail view's "Zuletzt
    verwendet" list."""
    if not DIR.exists():
        return []
    out = []
    for path in DIR.glob("*.json"):
        try:
            conv = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not conv.get("turns"):
            continue
        if project_id is not None and conv.get("project_id") != project_id:
            continue
        out.append(
            {
                "id": conv.get("id", path.stem),
                "title": conv.get("title"),
                "updated_at": conv.get("updated_at", conv.get("created_at", "")),
                "project_id": conv.get("project_id"),
            }
        )
    out.sort(key=lambda c: c["updated_at"], reverse=True)
    return out
