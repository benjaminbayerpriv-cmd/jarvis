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


def _index_new_line(source: str, line: str) -> None:
    """Best-effort: make a just-written line searchable via
    vector_memory.semantic_context_for immediately, not just after the
    next full reindex_all() backfill. Never lets an unreachable embedding
    model turn into a failed note/task/etc. — same fail-soft rule as
    everywhere else memory.py talks to the model."""
    from . import vector_memory  # local: vector_memory imports this module too

    try:
        vector_memory.index_entry(source, line)
    except Exception as exc:  # noqa: BLE001 - indexing must never break the write it followed
        print(f"[memory] Konnte neue Zeile nicht indizieren: {exc}")


def add_note(text: str) -> str:
    initialize()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- [{stamp}] {text}"
    with _lock, NOTES.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    _index_new_line("Notizen", line)
    return "Notiz in Obsidian gespeichert."


def add_task(text: str, status: str = "offen") -> str:
    initialize()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    marker = "x" if status == "erledigt" else " "
    with _lock, TASKS.open("a", encoding="utf-8") as handle:
        # A literal "\n" (two characters) was being written here instead of
        # an actual line break — the trailing double-space + real newline is
        # Markdown's soft-break convention, meant to keep each Obsidian
        # property (status::, erstellt::) on its own visual line within the
        # same list item. With a literal backslash-n, every task instead
        # showed up as one line with visible "\n" text right in the note.
        handle.write(f"- [{marker}] {text}  \n  status:: {status}  \n  erstellt:: {stamp}\n")
    _index_new_line("Aufgaben", f"- [{marker}] {text}")
    return f"Aufgabe als {status} in Obsidian gespeichert."


def remember_preference(text: str) -> str:
    initialize()
    line = f"- {text}"
    with _lock, PROFILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    _index_new_line("Profil", line)
    return "Präferenz in Obsidian gespeichert."


def add_knowledge(title: str, content: str) -> str:
    initialize()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "wissen"
    path = KNOWLEDGE / f"{slug}.md"
    path.write_text(_frontmatter("jarvis-knowledge", created=dt.date.today().isoformat(), tags="[jarvis]") + f"# {title}\n\n{content}\n", encoding="utf-8")
    # Indexed as one chunk (title + content), not line by line — unlike
    # notes/tasks, a knowledge entry is prose meant to be found as a whole.
    _index_new_line(f"Wissen/{slug}", f"{title}: {content}")
    return f"Wissen in [[Jarvis/Wissen/{slug}]] gespeichert."


def context_for(query: str, limit: int = 4) -> str:
    """Return only matching local memories for a model prompt.

    Tries semantic search first (vector_memory.semantic_context_for) —
    finds relevant memories that don't share a single word with the
    query, which plain substring matching below never could. Falls back
    to the original keyword match whenever semantic search is
    unavailable (embedding model not loaded in LM Studio, LM Studio
    itself unreachable, ...), so this degrades to prior behaviour rather
    than going silent.
    """
    initialize()

    from . import vector_memory  # local: vector_memory imports this module too

    try:
        semantic = vector_memory.semantic_context_for(query, limit=limit)
    except Exception as exc:  # noqa: BLE001 - a memory lookup must never break the chat turn
        print(f"[memory] Semantische Suche fehlgeschlagen, nutze Keyword-Suche: {exc}")
        semantic = None
    if semantic is not None:
        return semantic

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
