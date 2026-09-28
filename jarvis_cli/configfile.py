"""config.json — the settings that are JSON rather than .env (display name,
personality, weather city, code directory and coding agent).

Small enough to edit directly, but going through the CLI keeps a valid shape
and a backup instead of a hand-typed comma mistake.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import context as ctx

FILE = ctx.ROOT / "config.json"
PERSONALITIES = ("locker_direkt", "ruhig", "formell", "witzig", "knapp")
AGENTS = ("opencode", "claude", "codex")


def read_config() -> dict:
    if not FILE.exists():
        return {}
    try:
        data = json.loads(FILE.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config(updates: dict) -> dict:
    data = read_config()
    for key, value in updates.items():
        if value in (None, ""):
            data.pop(key, None)
        else:
            data[key] = value
    if FILE.exists():
        shutil.copy2(FILE, FILE.with_suffix(".json.bak"))
    FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def describe() -> str:
    data = read_config()
    return f"{data.get('name', 'Jarvis')} · {data.get('personality', '—')} · Stand {time.strftime('%H:%M:%S')}"


def path() -> Path:
    return FILE
