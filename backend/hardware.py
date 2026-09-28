"""Whether an LM Studio model fits into this PC's memory — checked before
loading it, because a model bigger than RAM + VRAM doesn't fail cleanly: it
pushes Windows into heavy swapping or takes LM Studio (and sometimes the
whole machine) down with it."""
from __future__ import annotations

import ctypes
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

from . import config

_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0

_sizes_cache: tuple[float, dict[str, int]] = (0.0, {})
_SIZES_TTL = 60.0

_blocked: dict[str, str] = {}


def find_lms_cli() -> str | None:
    """LM Studio's `lms` CLI is usually only on PATH after `lms bootstrap`,
    so its standard install location is checked directly too."""
    found = shutil.which("lms")
    if found:
        return found
    exe = "lms.exe" if sys.platform.startswith("win") else "lms"
    default = Path.home() / ".lmstudio" / "bin" / exe
    return str(default) if default.exists() else None


def _model_key(model_id: str) -> str:
    # LM Studio ids can carry a variant ("@q4_0") or instance (":2") suffix.
    return re.split(r"[@:]", model_id or "", maxsplit=1)[0].lower()


def lm_studio_root() -> str:
    """LM Studio's own origin (e.g. http://192.168.5.40:1234), derived from
    the OpenAI-compatible base URL Jarvis already talks to
    (http://.../v1) — the native /api/v1/* and legacy /api/v0/* endpoints
    live one level up from that."""
    base = config.LM_STUDIO_BASE_URL
    return base[: base.rfind("/v1")].rstrip("/") if base.endswith("/v1") else base.rstrip("/")


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def is_remote_lm_studio() -> bool:
    """Whether LM Studio's configured endpoint points at a different machine
    than the one Jarvis's own backend runs on. The model-size API works
    remotely; RAM-/VRAM-based checking was removed entirely, so this flag is
    informational only nowadays."""
    try:
        from urllib.parse import urlparse
        host = urlparse(lm_studio_root()).hostname or ""
    except ValueError:
        return False
    return host.lower() not in _LOCAL_HOSTS


def _v1_models() -> list[dict] | None:
    """Full GET /api/v1/models response (LM Studio >= 0.4.0's native REST
    API) — every model on disk, with its size AND currently loaded
    instances, in one plain HTTP call. Unlike the old `lms ls --json` CLI
    (which only ever sees LM Studio running on THIS machine) or the legacy
    /api/v0/models endpoint (loaded state only, no size), this is a normal
    request to the same LM Studio origin Jarvis already talks to for chat —
    it works exactly as well when LM Studio runs on a different machine on
    the network, no local `lms` binary required at all.
    Returns None (not []) on failure/older LM Studio, so callers can fall
    back to the legacy sources instead of concluding "no models"."""
    try:
        resp = requests.get(f"{lm_studio_root()}/api/v1/models", headers=config.lm_studio_headers(), timeout=4)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except (requests.RequestException, ValueError):
        return None


def _model_sizes() -> dict[str, int]:
    """Model key -> file size in bytes. Tries LM Studio's own v1 REST API
    first (works remotely, see _v1_models), falls back to the local `lms ls`
    CLI for older LM Studio versions or a same-machine setup without the v1
    API enabled."""
    global _sizes_cache
    stamp, cached = _sizes_cache
    if cached and time.monotonic() - stamp < _SIZES_TTL:
        return cached

    v1 = _v1_models()
    if v1 is not None:
        sizes = {}
        for m in v1:
            size = m.get("size_bytes")
            if not isinstance(size, int):
                continue
            if m.get("key"):
                sizes[_model_key(m["key"])] = size
            for inst in m.get("loaded_instances", []) or []:
                if inst.get("id"):
                    sizes[_model_key(inst["id"])] = size
        _sizes_cache = (time.monotonic(), sizes)
        return sizes

    lms = find_lms_cli()
    if not lms:
        return {}
    try:
        out = subprocess.run(
            [lms, "ls", "--json"], capture_output=True, text=True,
            encoding="utf-8", timeout=15, creationflags=_NO_WINDOW,
        ).stdout
        entries = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    sizes = {}
    for e in entries:
        size = e.get("sizeBytes")
        if not isinstance(size, int):
            continue
        for key in (e.get("modelKey"), e.get("path"), e.get("indexedModelIdentifier")):
            if key:
                sizes[_model_key(key)] = size
    _sizes_cache = (time.monotonic(), sizes)
    return sizes


def _loaded_models_raw() -> list[dict]:
    """Every loaded model instance as {"id", "size_bytes"} — real instance
    ids (the value POST /api/v1/models/unload takes), not the normalized
    keys _loaded_models() reduces them to. Prefers the v1 REST API (remote-
    capable, includes size); falls back to the legacy /api/v0/models (loaded
    state only, no size) for older LM Studio versions."""
    v1 = _v1_models()
    if v1 is not None:
        out = []
        for m in v1:
            size = m.get("size_bytes") if isinstance(m.get("size_bytes"), int) else 0
            for inst in m.get("loaded_instances", []) or []:
                if inst.get("id"):
                    out.append({"id": inst["id"], "size_bytes": size})
        return out
    try:
        resp = requests.get(f"{lm_studio_root()}/api/v0/models", headers=config.lm_studio_headers(), timeout=4)
        resp.raise_for_status()
        return [
            {"id": e["id"], "size_bytes": 0}
            for e in resp.json().get("data", [])
            if e.get("id") and e.get("state") == "loaded"
        ]
    except (requests.RequestException, ValueError):
        return []


def loaded_models_info() -> list[dict]:
    """Loaded models for the "andere Modelle entladen" UI: id + size (from
    the v1 REST API when available, else `lms ls`) + whether it's the one
    Jarvis is currently configured to chat with (that one isn't offered for
    unloading, unloading your own active model out from under yourself makes
    no sense here)."""
    sizes = _model_sizes()
    current = _model_key(config.LM_STUDIO_MODEL)
    return [
        {
            "id": e["id"],
            "size_bytes": e.get("size_bytes") or sizes.get(_model_key(e["id"]), 0),
            "is_current": _model_key(e["id"]) == current,
        }
        for e in _loaded_models_raw()
    ]


def check_models(model_ids: list[str], freeable_ids: list[str] | tuple = ()) -> dict[str, dict]:
    """Per model: does it fit into memory right now?

    `freeable_ids` are models that would be unloaded to make room (the one
    being switched away from) — their memory counts as available.

    Each verdict carries fits, fits_now, needed_bytes and a message — but
    since RAM-/VRAM-based blocking was removed by request, fits and
    fits_now are always True: LM Studio pages excess model memory into
    system RAM instead of failing, and it manages unloading the previous
    model itself. needed_bytes is the raw file size, purely informational
    (machines could be remote, so it's never compared against anything).
    """
    sizes = _model_sizes()
    _ = freeable_ids
    return {
        model_id: {
            "fits": True,
            "fits_now": True,
            "needed_bytes": sizes.get(_model_key(model_id), 0),
        }
        for model_id in model_ids
    }


def check_model(model_id: str, freeable_ids: list[str] | tuple = ()) -> dict:
    return check_models([model_id], freeable_ids)[model_id]


def block(model_id: str, message: str) -> None:
    _blocked[model_id] = message


def unblock_all() -> None:
    _blocked.clear()


def blocked_reason(model_id: str) -> str | None:
    return _blocked.get(model_id)
