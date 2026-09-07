"""Tracks the most recently resolved filesystem path.

A short follow-up that refers back to something by pronoun ("lösch ihn",
"ich wollte ja, dass du ihn löschst", "mach ihn auf") depends on correctly
carrying that reference forward from a few turns earlier — a small local
model repeatedly failed at exactly this (observed live: asked to delete a
folder it had itself just identified by name, it answered about notes
instead, never calling any folder tool at all). Rather than trying to
regex-match every way a human might phrase "it", this keeps the last
concretely resolved path as a plain fact and hands it to the model as
context on every turn — the model still has to recognize that a pronoun
refers to it, but the antecedent itself is no longer something it has to
dig out of the raw conversation text unaided.
"""

import time
from pathlib import Path

_target: Path | None = None
_at = 0.0

# Long enough to span a few back-and-forth turns (the folder got opened,
# discussed, then the user circles back to "lösch ihn doch") without
# lingering so long that some unrelated later "ihn" picks up a stale target.
_TTL_SECONDS = 180


def remember(path: Path) -> None:
    global _target, _at
    _target = path
    _at = time.time()


def hint() -> str:
    """A one-line system-context fact about the last resolved path, or ""."""
    if _target is None or time.time() - _at > _TTL_SECONDS:
        return ""
    kind = "Ordner" if _target.is_dir() else "Datei"
    return f"Zuletzt angesprochener {kind}: '{_target.name}' ({_target})."
