"""jarvis doctor — what is broken, in the order that matters.

Each check returns (state, label, detail, hint). The state is one of
"ok"/"warn"/"fail" and is what the dashboard colours come from, so a run
through this list is also a compact health summary of the whole setup.
"""

from __future__ import annotations

import platform
import sys

from . import context as ctx
from . import lmstudio, server
from .ui import ui

Check = tuple[str, str, str, str]


def check_python() -> Check:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info[:2] < (3, 10):
        return ("fail", "Python", f"{version} ist zu alt", "Python 3.10+ einbauen, dann neu öffnen")
    return ("ok", "Python", f"{version} ({platform.system()} {platform.machine()})", sys.executable)


def check_venv() -> Check:
    python = ctx.venv_python()
    if python is None:
        return ("fail", ".venv", "fehlt", "jarvis setup")
    version = ctx.venv_python_version()
    label = f"Python {'.'.join(map(str, version))}" if version else "vorhanden"
    return ("ok", ".venv", label, str(python))


def check_deps() -> Check:
    if not ctx.venv_python():
        return ("fail", "Pakete", "kein .venv", "jarvis setup")
    missing = ctx.missing_modules()
    if missing:
        return ("fail", "Pakete", f"{len(missing)} fehlen", ", ".join(missing[:6]))
    return ("ok", "Pakete", "alle importierbar", "")


def check_env() -> Check:
    if not ctx.ENV_FILE.exists():
        return ("fail", ".env", "fehlt", "jarvis setup")
    values = ctx.read_env()
    suspicious = [
        key for key in ("ELEVENLABS_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY")
        if values.get(key) and ctx.env(key) == ""
    ]
    if suspicious:
        return ("warn", ".env", "Platzhalter erkannt", f"{', '.join(suspicious)} — leer lassen")
    return ("ok", ".env", f"{len(values)} Einträge", str(ctx.ENV_FILE))


def check_lm_studio() -> Check:
    healthy, detail = lmstudio.health()
    return ("ok" if healthy else "fail", "LM Studio", "verbunden" if healthy else "nicht erreichbar",
            detail)


def check_token() -> Check:
    if not lmstudio.token():
        return ("ok", "LM-Studio-Token", "nicht gesetzt",
                "nur nötig mit „Require Authentication“ in LM Studio")
    good, message = lmstudio.verify_token(lmstudio.token())
    return ("ok" if good else "fail", "LM-Studio-Token",
            "gültig" if good else "wird abgelehnt", message)


def check_model() -> Check:
    model = lmstudio.model()
    loaded = lmstudio.loaded_models()
    if not model:
        return ("fail", "Modell", "nicht gesetzt", "jarvis model")
    if loaded and model not in loaded:
        return ("warn", "Modell", f"{model} ist nicht geladen",
                "jarvis model — oder in LM Studio laden")
    return ("ok", "Modell", model, f"{len(loaded)} geladen" if loaded else "")


def check_mcp() -> Check:
    if not ctx.env("JARVIS_MCP_TOKEN"):
        return ("warn", "MCP-Token", "noch nicht erzeugt", "jarvis mcp")
    if not lmstudio.native_api_ok():
        return ("warn", "MCP-Zugriff", "native API antwortet nicht",
                "LM Studio neu starten; Token prüfen")
    return ("ok", "MCP", f"Bereit auf Port {lmstudio.mcp_port()}", lmstudio.mcp_url())


def check_server() -> Check:
    if server.is_running():
        pid = server.running_pid()
        return ("ok", "Server", f"läuft{f' (PID {pid})' if pid else ''}", server.url())
    if server.port_busy():
        return ("fail", "Server", f"Port {server.port()} belegt",
                "andere Anwendung beenden oder JARVIS_PORT ändern")
    return ("warn", "Server", "gestoppt", "jarvis start")


def check_hotkey() -> Check:
    running = server.hotkey_running()
    combo = "Ctrl+Shift+J" if ctx.IS_WINDOWS else "Cmd+Shift+J"
    return ("ok" if running else "warn", "Hotkey",
            "läuft" if running else "gestoppt", combo)


def check_ram() -> Check:
    if not ctx.IS_WINDOWS:
        return ("ok", "Speicher", "nicht geprüft", "")
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return ("warn", "Speicher", "nicht abfragbar", "")
    gib = 1024 ** 3
    total, free, load = stat.ullTotalPhys / gib, stat.ullAvailPhys / gib, stat.dwMemoryLoad
    value = f"{total:.0f} GB, {free:.0f} GB frei ({load} % belegt)"
    if free < 2:
        return ("warn", "Speicher", value,
                "kaum Platz zum Laden — anderes schließen oder kleineres Modell")
    if total < 16:
        return ("warn", "Speicher", value, "unter 16 GB ein kleines Modell wählen")
    return ("ok", "Speicher", value, "")


def run(verbose: bool = True) -> tuple[int, int, int]:
    checks: list[Check] = [
        check_python(), check_venv(), check_deps(), check_env(),
        check_lm_studio(), check_token(), check_model(), check_mcp(),
        check_server(), check_hotkey(), check_ram(),
    ]
    if verbose:
        ui.heading("Diagnose")
        for kind, label, value, hint in checks:
            ui.status(kind, label, value, hint)
    fails = sum(1 for kind, *_ in checks if kind == "fail")
    warns = sum(1 for kind, *_ in checks if kind == "warn")
    ok = len(checks) - fails - warns
    if verbose:
        ui.out()
        if fails:
            ui.fail(f"{fails} Problem(e), {warns} Hinweis(e), {ok} in Ordnung.")
            ui.note("Die rot markierten Zeilen oben nennen jeweils den konkreten nächsten Schritt.")
        elif warns:
            ui.warn(f"{warns} Hinweis(e), {ok} in Ordnung — nichts blockiert den Start.")
        else:
            ui.ok("Alles in Ordnung.")
    return ok, warns, fails
