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


def _model_sizes() -> dict[str, int]:
    """Model key -> file size in bytes, from `lms ls --json`."""
    global _sizes_cache
    stamp, cached = _sizes_cache
    if cached and time.monotonic() - stamp < _SIZES_TTL:
        return cached
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


def _loaded_models() -> set[str]:
    base = config.LM_STUDIO_BASE_URL
    root = base[: base.rfind("/v1")].rstrip("/") if base.endswith("/v1") else base.rstrip("/")
    try:
        resp = requests.get(f"{root}/api/v0/models", timeout=4)
        resp.raise_for_status()
        return {
            _model_key(e["id"]) for e in resp.json().get("data", [])
            if e.get("id") and e.get("state") == "loaded"
        }
    except (requests.RequestException, ValueError):
        return set()


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
    """
    sizes = _model_sizes()
    loaded = _loaded_models()
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
