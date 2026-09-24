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

GIB = 1024 ** 3

# A GGUF file's size is only the weights — loading also allocates the KV
# cache for the context window plus runtime buffers. A rough rule of thumb,
# deliberately on the generous side: a false "doesn't fit" is an annoyance,
# a false "fits" is the crash this whole check exists to prevent.
_OVERHEAD_FACTOR = 1.2
_OVERHEAD_FIXED = 1 * GIB
# Kept free for Windows, Jarvis itself and Whisper, so the PC stays usable
# while the model is loaded.
_SYSTEM_RESERVE = 2 * GIB

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


def _system_ram() -> tuple[int, int]:
    """(total, available) bytes of physical RAM, or (0, 0) if unknown."""
    try:
        if sys.platform.startswith("win"):
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
            return 0, 0
        if sys.platform == "darwin":
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout)
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+)", vm).group(1))
            pages = sum(
                int(m.group(1))
                for key in ("Pages free", "Pages inactive", "Pages speculative")
                if (m := re.search(rf"{key}:\s+(\d+)", vm))
            )
            return total, pages * page
        meminfo = Path("/proc/meminfo").read_text()
        total = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) * 1024
        avail = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1)) * 1024
        return total, avail
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return 0, 0


def _gpu_vram() -> tuple[int, int]:
    """(total, free) bytes of dedicated NVIDIA VRAM, summed across GPUs.
    (0, 0) without an NVIDIA card — on Apple Silicon the GPU shares system
    RAM, which _system_ram already covers."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return 0, 0
    try:
        out = subprocess.run(
            [smi, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0, 0
    total = free = 0
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            total += int(parts[0]) * 1024 * 1024
            free += int(parts[1]) * 1024 * 1024
    return total, free


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
    than the one Jarvis's own backend runs on. Matters because _system_ram()/
    _gpu_vram() below read THIS machine's memory via local OS calls
    (ctypes/vm_stat/nvidia-smi) — there is no way to ask LM Studio's REST API
    for the remote machine's RAM/VRAM (checked: no such endpoint exists), so
    when LM Studio is remote, comparing a model's size against Jarvis's own
    machine's memory is comparing against the wrong computer entirely. Live
    observed: this produced a confidently wrong "nicht genug Speicher frei"
    for a model that fit fine on the actual (remote) machine."""
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
        resp = requests.get(f"{lm_studio_root()}/api/v1/models", timeout=4)
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
        resp = requests.get(f"{lm_studio_root()}/api/v0/models", timeout=4)
        resp.raise_for_status()
        return [
            {"id": e["id"], "size_bytes": 0}
            for e in resp.json().get("data", [])
            if e.get("id") and e.get("state") == "loaded"
        ]
    except (requests.RequestException, ValueError):
        return []


def _loaded_models() -> set[str]:
    return {_model_key(e["id"]) for e in _loaded_models_raw()}


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


def _gb(n: float) -> str:
    return f"{n / GIB:.1f}".replace(".", ",")


def check_models(model_ids: list[str], freeable_ids: list[str] | tuple = ()) -> dict[str, dict]:
    """Per model: does it fit into memory right now?

    `freeable_ids` are models that would be unloaded to make room (the one
    being switched away from) — their memory counts as available.

    Each verdict: fits (loadable at all), fits_now (without unloading
    anything first), needed_bytes, and a German message when it doesn't fit.
    A model whose size or this PC's memory can't be determined is always
    allowed — the check must never block a model just because it's blind.
    Also always allowed when LM Studio runs on a different machine (see
    is_remote_lm_studio): THIS machine's memory says nothing about whether
    it fits on the machine that actually loads it.
    """
    sizes = _model_sizes()
    loaded = _loaded_models()
    if is_remote_lm_studio():
        return {
            model_id: {"fits": True, "fits_now": True, "needed_bytes": sizes.get(_model_key(model_id), 0)}
            for model_id in model_ids
        }
    ram_total, ram_free = _system_ram()
    vram_total, vram_free = _gpu_vram()
    capacity = ram_total + vram_total - _SYSTEM_RESERVE
    free_now = ram_free + vram_free - _SYSTEM_RESERVE
    freeable = sum(
        sizes.get(_model_key(m), 0) for m in freeable_ids
        if m and _model_key(m) in loaded
    )

    verdicts = {}
    for model_id in model_ids:
        key = _model_key(model_id)
        size = sizes.get(key)
        if key in loaded or not size or not ram_total:
            verdicts[model_id] = {"fits": True, "fits_now": True, "needed_bytes": size or 0}
            continue
        needed = size * _OVERHEAD_FACTOR + _OVERHEAD_FIXED
        fits_now = needed <= free_now
        fits = needed <= min(free_now + freeable, capacity)
        verdict = {"fits": fits, "fits_now": fits_now, "needed_bytes": int(needed)}
        if not fits:
            if needed > capacity:
                verdict["message"] = (
                    f"Die PC-Spezifikationen reichen nicht aus, um {model_id} zu laden: "
                    f"Das Modell braucht etwa {_gb(needed)} GB, dein PC hat insgesamt "
                    f"{_gb(ram_total + vram_total)} GB (Arbeitsspeicher und Grafikspeicher). "
                    "Wähl bitte ein kleineres Modell."
                )
            else:
                verdict["message"] = (
                    f"Gerade ist nicht genug Speicher frei, um {model_id} zu laden: "
                    f"Das Modell braucht etwa {_gb(needed)} GB, frei sind nur "
                    f"{_gb(max(free_now + freeable, 0))} GB. Schließ andere Programme "
                    "und versuch es nochmal, oder wähl ein kleineres Modell."
                )
        verdicts[model_id] = verdict
    return verdicts


def check_model(model_id: str, freeable_ids: list[str] | tuple = ()) -> dict:
    return check_models([model_id], freeable_ids)[model_id]


def block(model_id: str, message: str) -> None:
    _blocked[model_id] = message


def unblock_all() -> None:
    _blocked.clear()


def blocked_reason(model_id: str) -> str | None:
    return _blocked.get(model_id)
