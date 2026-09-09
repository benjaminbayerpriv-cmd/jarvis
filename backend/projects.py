"""JSON-backed store for Projects — the sidebar's "Projekte" grid.

Just name/description/tag/date for now, one JSON file per project,
mirroring conversations.py's storage shape. No linkage to conversations
yet — that's a separate feature to wire up once this exists.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from pathlib import Path

DIR = Path(__file__).resolve().parent / "projects"
_lock = threading.Lock()


def new_id() -> str:
    return str(uuid.uuid4())


def _path(project_id: str) -> Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_") or "project"
    return DIR / f"{safe}.json"


def create(name: str, description: str = "", tag: str = "") -> dict:
    with _lock:
        DIR.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now().isoformat(timespec="seconds")
        project = {
            "id": new_id(),
            "name": name.strip(),
            "description": description.strip(),
            "tag": tag.strip(),
            "created_at": now,
        }
        _path(project["id"]).write_text(
            json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return project


def list_projects() -> list[dict]:
    """Newest first."""
    if not DIR.exists():
        return []
    out = []
    for path in DIR.glob("*.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    out.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return out


def delete(project_id: str) -> None:
    path = _path(project_id)
    if path.exists():
        path.unlink()
