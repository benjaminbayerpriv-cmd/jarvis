"""JSON-backed store for Projects — the sidebar's "Projekte" grid.

Every project is backed by a real folder on disk (``dir``): created fresh or
pointed at an existing one when the project is made, and that's where its
conversations live too — see conversations.py's ``base_dir`` parameter and
main.py's ``_project_chats_dir()``. The project record itself (name,
description, tag, dir, dates) still lives in its own small JSON file here,
mirroring conversations.py's storage shape.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from pathlib import Path

DIR = Path(__file__).resolve().parent / "projects"
_lock = threading.Lock()

# Conversations belonging to a project are stored under this subfolder of
# the project's own directory — keeps them out of the way of whatever else
# lives in that folder, without hiding them (no leading dot).
CHATS_SUBDIR = "jarvis-chats"


def new_id() -> str:
    return str(uuid.uuid4())


def _path(project_id: str) -> Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_") or "project"
    return DIR / f"{safe}.json"


def resolve_dir(raw_dir: str) -> Path:
    """Turns whatever the user typed/pasted into an absolute path, creating
    it if it doesn't exist yet — covers "erstellen oder auswählen" (create
    or pick an existing one) with the same text field. Raises OSError (e.g.
    permission denied, invalid path) for the caller to turn into a 422."""
    path = Path(raw_dir.strip()).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def chats_dir(project: dict) -> Path | None:
    # A project made before this field existed has no "dir" — fall back to
    # None (the caller then uses the default central store) instead of
    # raising, so an old project record doesn't 500 the whole chat request.
    d = project.get("dir")
    return Path(d) / CHATS_SUBDIR if d else None


def create(dir: str, name: str = "", description: str = "", tag: str = "") -> dict:
    resolved = resolve_dir(dir)
    with _lock:
        DIR.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now().isoformat(timespec="seconds")
        project = {
            "id": new_id(),
            "name": name.strip() or resolved.name,
            "description": description.strip(),
            "tag": tag.strip(),
            "dir": str(resolved),
            "pinned": False,
            "created_at": now,
            "updated_at": now,
        }
        _path(project["id"]).write_text(
            json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return project


def get(project_id: str) -> dict | None:
    path = _path(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def update(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    pinned: bool | None = None,
) -> dict | None:
    with _lock:
        path = _path(project_id)
        if not path.exists():
            return None
        project = json.loads(path.read_text(encoding="utf-8"))
        if name is not None:
            project["name"] = name.strip()
        if description is not None:
            project["description"] = description.strip()
        if pinned is not None:
            project["pinned"] = pinned
        project["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
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
    # Only removes the project *record* — never touches the linked folder
    # or the chats inside it. Deleting someone's actual files because they
    # clicked "remove from the project list" would be a nasty surprise.
    path = _path(project_id)
    if path.exists():
        path.unlink()
