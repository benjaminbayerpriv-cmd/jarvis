"""Deterministic confirm-then-act state for destructive tool calls.

A natural-language "Soll ich X tun?" -> "Ja!" exchange used to depend
entirely on the model correctly remembering, one round-trip later and after
any amount of unrelated chatter in between, what it had just asked and then
actually calling the right tool again with the right arguments — a small
local model reliably lost that thread (observed live: it asked to delete a
folder, the user said "ja", and it just replied "Alles klar!" with no tool
call at all).

This turns the pending action into real state instead of something the
model has to re-derive from prose each time. A plain yes/no reply is
resolved right here, in code, before the model is even consulted — so it
can't misfire regardless of exact phrasing, or how confused the surrounding
conversation got. The offer only lives for the one message right after it's
made; anything else (a change of subject, a delayed answer) lets it lapse
rather than risking it firing on some unrelated later "ja".
"""

from __future__ import annotations

import re
from typing import Callable

_YES_RE = re.compile(
    r"^\s*(ja+|jup+|jep+|klar|genau|korrekt|okay|ok|mach'?s?|mach das|mach es|"
    r"los|bitte|tu es|tu's|do it|yes|yep|jo)\W*$",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"^\s*(nein+|nope|nee+|lass(?: mal)?|abbrechen|stopp?|nicht|no)\W*$",
    re.IGNORECASE,
)

_pending: dict | None = None


def propose(question: str, run: Callable[[], str]) -> str:
    """Register a pending confirmable action; returns the question to speak.

    `run` is called with no arguments if the very next user message is a
    plain yes.
    """
    global _pending
    _pending = {"run": run}
    return question


def is_pending() -> bool:
    """Whether a confirmation was just registered and is awaiting a reply."""
    return _pending is not None


def resolve(user_message: str) -> str | None:
    """Resolve a pending action against `user_message`.

    Returns the reply text if this message settled a pending action
    (executed or cancelled it) — the caller should use that as the whole
    reply and skip the model entirely for this turn. Returns None if there
    was nothing pending, or the message wasn't a plain yes/no; either way
    the pending action is cleared, since it's only ever honored for the one
    message right after it was proposed.
    """
    global _pending
    if _pending is None:
        return None
    pending, _pending = _pending, None

    text = (user_message or "").strip()
    if _YES_RE.match(text):
        return pending["run"]()
    if _NO_RE.match(text):
        return "Alles klar, abgebrochen."
    return None
