"""Local, Obsidian-compatible long-term memory for Jarvis."""

from __future__ import annotations

import datetime as dt
import re
import threading
from pathlib import Path

from . import config

ROOT = config.ROOT_DIR / "Jarvis"
KNOWLEDGE = ROOT / "Wissen"
JOURNAL = ROOT / "Tagebuch"
PROFILE = ROOT / "Profil.md"
TASKS = ROOT / "Aufgaben.md"
NOTES = ROOT / "Notizen.md"
_lock = threading.Lock()


def _frontmatter(kind: str, **fields: str) -> str:
    rows = ["---", f"type: {kind}"]
    rows.extend(f"{key}: {value}" for key, value in fields.items())
    return "\n".join(rows) + "\n---\n\n"


def initialize() -> None:
    """Create a portable Markdown vault layout and import legacy notes once."""
    with _lock:
        KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        JOURNAL.mkdir(parents=True, exist_ok=True)
        if not PROFILE.exists():
            PROFILE.write_text(_frontmatter("jarvis-profile", updated=dt.date.today().isoformat()) + "# Profil\n", encoding="utf-8")
        if not TASKS.exists():
            TASKS.write_text(_frontmatter("jarvis-tasks", updated=dt.date.today().isoformat()) + "# Aufgaben\n", encoding="utf-8")
        if not NOTES.exists():
            imported = config.NOTES_FILE.read_text(encoding="utf-8") if config.NOTES_FILE.exists() else ""
            NOTES.write_text(
                _frontmatter("jarvis-notes", imported_from="jarvis_notes.md") + "# Notizen\n\n" + imported,
                encoding="utf-8",
            )


def add_note(text: str) -> str:
    initialize()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with _lock, NOTES.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{stamp}] {text}\n")
    return "Notiz in Obsidian gespeichert."


def add_task(text: str, status: str = "offen") -> str:
    initialize()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    marker = "x" if status == "erledigt" else " "
    with _lock, TASKS.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{marker}] {text}  \\n  status:: {status}  \\n  erstellt:: {stamp}\n")
    return f"Aufgabe als {status} in Obsidian gespeichert."


def remember_preference(text: str) -> str:
    initialize()
    with _lock, PROFILE.open("a", encoding="utf-8") as handle:
        handle.write(f"- {text}\n")
    return "Präferenz in Obsidian gespeichert."


def add_knowledge(title: str, content: str) -> str:
    initialize()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "wissen"
    path = KNOWLEDGE / f"{slug}.md"
    path.write_text(_frontmatter("jarvis-knowledge", created=dt.date.today().isoformat(), tags="[jarvis]") + f"# {title}\n\n{content}\n", encoding="utf-8")
    return f"Wissen in [[Jarvis/Wissen/{slug}]] gespeichert."


def log_summary(user_text: str, assistant_text: str) -> None:
    """Store a concise daily trace, never an unbounded raw chat transcript."""
    initialize()
    day = JOURNAL / f"{dt.date.today().isoformat()}.md"
    if not day.exists():
        day.write_text(_frontmatter("jarvis-daily", date=dt.date.today().isoformat()) + f"# {dt.date.today().isoformat()}\n", encoding="utf-8")
    clean_user = " ".join(user_text.split())[:180]
    clean_reply = " ".join(assistant_text.split())[:220]
    with _lock, day.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- Anfrage: {clean_user}\n  Ergebnis: {clean_reply}\n")


def context_for(query: str, limit: int = 4) -> str:
    """Return only matching local memories for a model prompt."""
    initialize()
    words = {word.lower() for word in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", query)}
    if not words:
        return ""
    matches: list[str] = []
    for path in (PROFILE, TASKS, NOTES, *KNOWLEDGE.glob("*.md")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if any(word in line.lower() for word in words):
                    matches.append(f"[[{path.relative_to(config.ROOT_DIR).with_suffix('')}]] {line.strip()}")
                    if len(matches) >= limit:
                        return "\n".join(matches)
        except OSError:
            continue
    return "\n".join(matches)
