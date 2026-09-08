"""Semantic search over the Obsidian vault (backend/memory.py), replacing
memory.context_for()'s plain substring match with real similarity search.

Deliberately not a full vector database (ChromaDB and friends) — the vault
is a personal notes collection, realistically a few hundred to a few
thousand lines, not a corpus that needs one. A flat JSON index plus numpy
cosine similarity (numpy is already a dependency, via supertonic) covers
that comfortably without pulling in ChromaDB's ~40 extra packages
(gRPC, Kubernetes client, OpenTelemetry, ...) or risking an onnxruntime
version conflict with supertonic, which already pins its own.

Embeddings come from LM Studio's OpenAI-compatible /embeddings endpoint —
the same local server already running the chat model, just with an
embedding model loaded too (see config.EMBEDDING_MODEL). If that model
isn't loaded, every function here fails soft (returns None/[]/""), and
memory.context_for() falls back to its original keyword match.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

import numpy as np
import requests

from . import config, memory

INDEX_FILE = Path(__file__).resolve().parent / "vector_index" / "index.json"
_lock = threading.Lock()

# Populated lazily from the index file's own entries — avoids re-embedding
# unchanged lines every time reindex_all() runs (e.g. on every startup).
_cache: dict | None = None


def embed(text: str, task: str = "document") -> list[float] | None:
    """A single embedding vector for `text`, or None if the embedding
    model isn't reachable/loaded — callers must treat that as "semantic
    search unavailable right now", never as an error to surface.

    `task` picks nomic-embed-text's documented instruction prefix
    ("search_query: " / "search_document: ") — without it, queries and
    stored content land in different, less comparable regions of the
    embedding space; this model was specifically trained expecting it.
    """
    prefix = "search_query: " if task == "query" else "search_document: "
    try:
        resp = requests.post(
            f"{config.LM_STUDIO_BASE_URL}/embeddings",
            json={"model": config.EMBEDDING_MODEL, "input": prefix + text},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        print(f"[memory] Embedding-Modell nicht erreichbar, semantische Suche pausiert: {exc}")
        return None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if INDEX_FILE.exists():
        try:
            _cache = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save() -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def line_id(source: str, text: str) -> str:
    """A stable id for one vault line, derived from its content rather
    than its position — index_entry() (called right after memory.py
    writes a line) and reindex_all() (scanning the same line back out of
    the file later) need to agree on the same id for the same text, or
    the backfill would just re-embed everything a second time under a
    different key instead of recognizing it as already indexed."""
    return f"{source}#{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def index_entry(source: str, text: str) -> None:
    """Embed and store one line of vault content. Called right after
    memory.py writes it, so new notes/tasks/journal entries become
    searchable immediately instead of waiting for the next reindex."""
    text = text.strip()
    if not text:
        return
    entry_id = line_id(source, text)
    with _lock:
        if entry_id in _load():
            return
    vector = embed(text)
    if vector is None:
        return
    with _lock:
        cache = _load()
        cache[entry_id] = {"text": text, "source": source, "vector": vector}
        _save()


# Frontmatter/heading noise that would otherwise get embedded as if it
# were real content — skipped rather than indexed.
_SKIP_LINE_RE = re.compile(r"^\s*(---|#|type:|updated:|created:|date:|tags:|imported_from:)")


def reindex_all() -> None:
    """One-time (well, once-per-new-content) backfill so pre-existing
    vault content is searchable too, not just what's written after this
    feature landed. Safe to call repeatedly — already-indexed lines
    (matched by id) are skipped without re-embedding them."""
    memory.initialize()
    with _lock:
        cache = _load()
        existing_ids = set(cache.keys())

    sources: list[tuple[str, Path]] = [
        ("Profil", memory.PROFILE),
        ("Aufgaben", memory.TASKS),
        ("Notizen", memory.NOTES),
    ]
    sources += [(f"Wissen/{p.stem}", p) for p in memory.KNOWLEDGE.glob("*.md")]
    sources += [(f"Tagebuch/{p.stem}", p) for p in memory.JOURNAL.glob("*.md")]

    added = 0
    for source, path in sources:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or _SKIP_LINE_RE.match(line):
                continue
            if line_id(source, line) in existing_ids:
                continue
            index_entry(source, line)
            added += 1
    if added:
        print(f"[memory] {added} Vault-Zeile(n) neu indiziert für die semantische Suche.")


def semantic_context_for(query: str, limit: int = 4) -> str | None:
    """Top `limit` semantically similar vault lines for `query`, formatted
    like memory.context_for()'s keyword matches. Returns None (not "") when
    semantic search itself is unavailable, so the caller can tell that
    apart from "available, but genuinely nothing relevant"."""
    query_vector = embed(query, task="query")
    if query_vector is None:
        return None

    with _lock:
        cache = _load()
    if not cache:
        return ""

    query_arr = np.array(query_vector)
    query_norm = np.linalg.norm(query_arr)
    if query_norm == 0:
        return ""

    scored = []
    for entry in cache.values():
        vec = np.array(entry["vector"])
        denom = query_norm * np.linalg.norm(vec)
        similarity = float(np.dot(query_arr, vec) / denom) if denom else 0.0
        scored.append((similarity, entry))

    # No absolute cutoff: measured live, this (small, local) embedding
    # model puts even unrelated German sentences around 0.55-0.65 cosine
    # similarity, so a fixed threshold either let irrelevant lines through
    # or hid genuinely relevant ones — the score isn't meaningful in
    # absolute terms, only in relative rank. Same recall-first philosophy
    # the original keyword match already had (any hit was included, no
    # quality filter) — the model reading the prompt is what judges
    # relevance, same as it always did.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    matches = [f"[[Jarvis/{entry['source']}]] {entry['text']}" for _similarity, entry in scored[:limit]]
    return "\n".join(matches)
