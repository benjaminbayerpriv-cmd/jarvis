"""Starting, stopping and inspecting the Jarvis server and the hotkey
listener.

The server is deliberately not run as a child of the CLI: a background
process that dies with its parent, or that shares a console with a menu, is
the classic "Jarvis vanished when I closed the terminal" problem. Instead
it's started detached with a pid file, its output goes to .jarvis/server.log
and stopping it goes through the backend's own /shutdown endpoint first, so
no PID guessing is involved in the normal case.
"""

from __future__ import annotations

import os
import subprocess
import time

from . import context as ctx
from . import lmstudio
from .ui import ui

STARTUP_TIMEOUT = 180
PROJECT_DIR = ctx.ROOT / "launcher"


def host() -> str:
    # JARVIS_HOST is the bind address; a wildcard bind (LAN access) is still
    # reached on loopback — connecting to 0.0.0.0 fails on Windows.
    value = ctx.env("JARVIS_HOST")
    return "127.0.0.1" if value in ("", "0.0.0.0", "::") else value


def port() -> int:
    try:
        return int(ctx.env("JARVIS_PORT") or 8000)
    except ValueError:
        return 8000


def url() -> str:
    return f"http://{host()}:{port()}"


def server_url() -> str:
    return url()


# ----------------------------------------------------------------- probing
def api(path: str, timeout: float = 3.0, method: str = "GET"):
    return ctx.http_json(f"{url()}{path}", timeout=timeout, method=method)


def is_running() -> bool:
    """The backend answers GET /settings with JSON; anything else on the port
    is somebody else's service."""
    payload, error = api("/settings", timeout=1.5)
    return error is None and isinstance(payload, dict) and "lm_studio_base_url" in payload


def running_pid() -> int:
    pid = ctx.read_pid(ctx.SERVER_PID)
    return pid if pid and ctx.process_alive(pid) else 0


def port_busy() -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((host(), port())) == 0


def port_owner(port_no: int) -> int:
    """PID that currently listens on the given port (0 if none). Reliable even
    when the backend re-execed itself and our pid file points at a dead pid."""
    try:
        if ctx.IS_WINDOWS:
            script = ("Get-NetTCPConnection -LocalPort {p} -State Listen -ErrorAction SilentlyContinue "
                      "| Select-Object -ExpandProperty OwningProcess -First 1")
            result = subprocess.run(["powershell", "-NoProfile", "-Command", script.format(p=port_no)],
                                    capture_output=True, text=True, timeout=10,
                                    encoding="utf-8", errors="replace", creationflags=ctx.no_window())
            return int(result.stdout.strip())
        result = subprocess.run(["lsof", "-t", f"-iTCP:{port_no}", "-sTCP:LISTEN"],
                                capture_output=True, text=True, timeout=10)
        return int(result.stdout.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        # No lsof/PowerShell, a hung PowerShell, or nobody listening.
        return 0


def status() -> dict:
    running = is_running()
    return {
        "running": running,
        "pid": running_pid(),
        "url": url(),
        "hotkey": hotkey_running(),
        "autostart": autostart_installed(),
    }


def summary_lines() -> list[tuple[str, str, str, str]]:
    """(state, label, value, hint) rows for the dashboard."""
    running = is_running()
    pid = running_pid()
    rows = [(
        "ok" if running else "fail",
        "Jarvis-Server",
        "läuft" if running else "gestoppt",
        f"{url()}" + (f"  (PID {pid})" if pid else ("  (fremd gestartet)" if running else "")),
    )]
    healthy, detail = lmstudio.health()
    rows.append((
        "ok" if healthy else "fail", "LM Studio", "verbunden" if healthy else "nicht erreichbar", detail,
    ))
    rows.append((
        "ok" if lmstudio.token() else "warn", "LM-Studio-Token",
        "gesetzt" if lmstudio.token() else "nicht gesetzt", "nur bei „Require Authentication“ nötig",
    ))
    venv = ctx.venv_python()
    if venv:
        rows.append(("ok", "Python-Umgebung", ".venv vorhanden", str(venv)))
    elif ctx.backend_python():
        rows.append(("warn", "Python-Umgebung", "kein .venv",
                     f"läuft mit System-Python — jarvis setup legt .venv an"))
    else:
        rows.append(("fail", "Python-Umgebung", "fehlt", "jarvis setup"))
    mcp = ctx.env("JARVIS_MCP_TOKEN")
    rows.append((
        "ok" if mcp else "warn", "MCP-Token", "gesetzt" if mcp else "wird beim ersten Start erzeugt", "",
    ))
    hotkey = hotkey_running()
    rows.append((
        "ok" if hotkey else "warn", "Hotkey-Listener",
        "läuft" if hotkey else "gestoppt", "Ctrl+Shift+J" if ctx.IS_WINDOWS else "Cmd+Shift+J",
    ))
    auto = autostart_installed()
    rows.append((
        "ok" if auto else "warn", "Autostart", "aktiv" if auto else "aus", "",
    ))
    return rows


def dashboard() -> None:
    ui.heading("Status")
    for kind, label, value, hint in summary_lines():
        ui.status(kind, label, value, hint)


# ----------------------------------------------------------------- control
def start(open_browser: bool = True, wait: bool = True, quiet: bool = False) -> bool:
    if is_running():
        if not quiet:
            ui.ok(f"Jarvis läuft bereits auf {url()}")
        return True
    python = ctx.backend_python()
    if python is None:
        ui.fail("Keine lauffähige Python-Umgebung — erst „jarvis setup“ ausführen.")
        return False
    if port_busy():
        ui.fail(f"Port {port()} ist belegt, aber antwortet kein Jarvis. "
               f"Andere Anwendung beenden oder JARVIS_PORT in {ctx.ENV_FILE.name} ändern.")
        return False

    ctx.ensure_state_dir()
    if not quiet:
        ui.info(f"Starte Jarvis ({'venv' if ctx.venv_python() else 'System-Python'}) …")
    process = ctx.run_hidden([str(python), "-m", "backend.main"], log=ctx.SERVER_LOG)
    if process is None:
        ui.fail(f"Start fehlgeschlagen — {python} konnte nicht ausgeführt werden.")
        return False
    ctx.write_pid(ctx.SERVER_PID, process.pid)

    if not wait:
        ui.ok(f"gestartet (PID {process.pid}) — bereit in {url()}")
        return True

    # The first start also loads Whisper and prefills the model, so this can
    # legitimately take a minute; say so instead of looking hung.
    deadline = time.time() + STARTUP_TIMEOUT
    with ui.progress("Server startet (Whisper-Modell wird geladen) …", total=STARTUP_TIMEOUT) as bar:
        while time.time() < deadline:
            if is_running():
                bar.finish()
                ui.ok(f"Jarvis läuft auf {url()}")
                break
            if process.poll() is not None:
                ui.fail("Der Server ist beim Starten abgestürzt — die letzten Zeilen:")
                ui.lines("\n".join(ctx.tail(ctx.SERVER_LOG, 15)))
                return False
            time.sleep(0.5)
            bar.set(int(STARTUP_TIMEOUT - (deadline - time.time())))
        else:
            ui.warn(f"Noch nicht erreichbar nach {STARTUP_TIMEOUT}s. Log: jarvis logs")
            return False

    if open_browser:
        ctx.open_url(url())
        ui.info(f"Browser geöffnet: {url()}")
    return True


def stop() -> bool:
    if not is_running():
        stale = running_pid()
        if stale:
            ctx.stop_pid(stale, "Server")
        ctx.SERVER_PID.unlink(missing_ok=True)
        ui.info("Jarvis läuft nicht.")
        return False
    payload, error = api("/shutdown", timeout=3, method="POST")
    if error is None:
        for _ in range(30):
            if not is_running():
                break
            time.sleep(0.2)
    # The backend may have re-execed itself after we recorded the pid, or the
    # MCP uvicorn may outlive the /shutdown handler. Whoever still owns the
    # port has to go or the next "start" will bounce off a dead listener.
    pid = port_owner(port())
    if not pid:
        pid = running_pid()
    if pid and ctx.process_alive(pid):
        ui.step(f"Server beendet den Port nicht — beende PID {pid} …")
        ctx.stop_pid(pid, "Server")
    ctx.SERVER_PID.unlink(missing_ok=True)
    ui.ok("Jarvis beendet.")
    return True


def restart(open_browser: bool = True, wait: bool = True, quiet: bool = False) -> bool:
    stop()
    time.sleep(0.5)
    return start(open_browser=open_browser, wait=wait, quiet=quiet)


def logs(lines: int = 60, follow: bool = False) -> None:
    ui.heading(f"Server-Log ({ctx.SERVER_LOG.relative_to(ctx.ROOT)})")
    if not ctx.SERVER_LOG.exists():
        ui.info("Noch kein Log — der Server wurde über die CLI noch nicht gestartet.")
        return
    for line in ctx.tail(ctx.SERVER_LOG, lines):
        ui.out("  " + ui.paint(ui.truncate(line, ui.width - 2), "grey"))
    if not follow:
        return
    ui.out()
    ui.note("Strg+C beendet das Mitlesen (der Server läuft weiter).")
    with ctx.SERVER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        try:
            while True:
                line = handle.readline()
                if line:
                    ui.write(ui.truncate(line.rstrip(), ui.width - 2) + "\n")
                else:
                    time.sleep(0.4)
        except KeyboardInterrupt:
            ui.out()


def open_ui() -> None:
    if not is_running():
        ui.warn("Jarvis läuft gerade nicht — erst „jarvis start“.")
        return
    ctx.open_url(url())
    ui.ok(f"Browser geöffnet: {url()}")


# ------------------------------------------------------------------ hotkey
def hotkey_running() -> bool:
    """The pid file first, then a process-table lookup — a hotkey started via
    start_jarvis_windows.cmd or the .exe has no pid file of ours."""
    pid = ctx.read_pid(ctx.HOTKEY_PID)
    if pid and ctx.process_alive(pid):
        return True
    try:
        if ctx.IS_WINDOWS:
            script = (
                "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                "| Where-Object { $_.CommandLine -like '*hotkey_listener*' }).ProcessId"
            )
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=30,
                                 errors="replace", creationflags=ctx.no_window())
            return out.returncode == 0 and out.stdout.strip().isdigit()
        out = subprocess.run(["pgrep", "-f", "hotkey_listener"], capture_output=True, text=True,
                             timeout=20, errors="replace")
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # A slow/hung PowerShell or a missing pgrep must not take the whole
        # status screen down — "not running" is the safe answer.
        return False


def hotkey_start() -> bool:
    python = ctx.backend_python()
    if python is None:
        ui.fail("Keine lauffähige Python-Umgebung — erst „jarvis setup“ ausführen.")
        return False
    process = ctx.run_hidden([str(python), "launcher/hotkey_listener.py"], log=ctx.HOTKEY_LOG)
    if process is None:
        ui.fail("Hotkey-Listener konnte nicht gestartet werden.")
        return False
    ctx.write_pid(ctx.HOTKEY_PID, process.pid)
    time.sleep(0.8)
    if not ctx.process_alive(process.pid):
        ui.fail("Hotkey-Listener ist sofort wieder abgestürzt:")
        ui.lines("\n".join(ctx.tail(ctx.HOTKEY_LOG, 10)))
        return False
    combo = "Ctrl+Shift+J" if ctx.IS_WINDOWS else "Cmd+Shift+J"
    ui.ok(f"Hotkey-Listener läuft ({combo} holt Jarvis aus dem Hintergrund).")
    if ctx.IS_MACOS:
        ui.note("Unter macOS braucht der Listener einmalig „Input Monitoring“ unter "
                "Systemeinstellungen → Datenschutz & Sicherheit.")
    return True


def hotkey_stop() -> bool:
    pid = ctx.read_pid(ctx.HOTKEY_PID)
    if not pid or not ctx.process_alive(pid):
        ctx.HOTKEY_PID.unlink(missing_ok=True)
        ui.info("Hotkey-Listener läuft nicht.")
        return False
    ctx.stop_pid(pid, "Hotkey")
    ctx.HOTKEY_PID.unlink(missing_ok=True)
    ui.ok("Hotkey-Listener beendet.")
    return True


# --------------------------------------------------------------- autostart
TASK_SERVER = "Jarvis Server"
TASK_HOTKEY = "Jarvis Hotkey"
PLIST_SERVER = "com.jarvis.server"
PLIST_HOTKEY = "com.jarvis.hotkey"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          errors="replace", creationflags=ctx.no_window())


def autostart_installed() -> bool:
    if ctx.IS_WINDOWS:
        listing = _schtasks("/query", "/fo", "LIST", "/v")
        return TASK_SERVER in (listing.stdout or "") and TASK_HOTKEY in (listing.stdout or "")
    home = ctx.Path.home()
    return (home / "Library/LaunchAgents" / f"{PLIST_SERVER}.plist").exists()


def autostart_enable() -> bool:
    if ctx.IS_WINDOWS:
        ok = True
        for name, script in ((TASK_SERVER, "start_server.bat"), (TASK_HOTKEY, "start_hotkey.bat")):
            # Quoted: an unquoted path with a space ("C:\Users\Max Muster\…")
            # is stored as-is and the task then fails to start at login.
            target = f'"{PROJECT_DIR / script}"'
            _schtasks("/delete", "/tn", name, "/f")
            result = _schtasks("/create", "/tn", name, "/tr", target, "/sc", "onlogon", "/rl", "highest")
            if result.returncode == 0:
                ui.ok(f"Autostart eingerichtet: {name}")
            else:
                ui.fail(f"{name}: {(result.stderr or result.stdout).strip()}")
                ok = False
        return ok
    script = ctx.ROOT / "launcher" / "install_macos_autostart.sh"
    if not script.exists():
        ui.fail("launcher/install_macos_autostart.sh fehlt.")
        return False
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                            errors="replace", cwd=str(ctx.ROOT))
    if result.returncode == 0:
        ui.ok("Autostart eingerichtet (zwei LaunchAgents).")
        return True
    ui.fail("Autostart fehlgeschlagen:")
    ui.lines(result.stdout + result.stderr)
    return False


def autostart_disable() -> bool:
    if ctx.IS_WINDOWS:
        for name in (TASK_SERVER, TASK_HOTKEY):
            _schtasks("/delete", "/tn", name, "/f")
        ui.ok("Autostart entfernt (geplante Aufgaben gelöscht).")
        return True
    for label in (PLIST_SERVER, PLIST_HOTKEY):
        # No shell here, so "~" would not be expanded and the unload silently
        # did nothing; autostart_installed() also keys off the plist file.
        plist = ctx.Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        subprocess.run(["launchctl", "unload", str(plist)],
                       capture_output=True, text=True, errors="replace")
        plist.unlink(missing_ok=True)
    ui.ok("Autostart deaktiviert (LaunchAgents entladen und entfernt).")
    return True


def build_exe() -> bool:
    if not ctx.IS_WINDOWS:
        ui.info("Nur unter Windows relevant — dort: launcher\\build_exe.bat")
        return False
    script = ctx.ROOT / "launcher" / "build_exe.bat"
    if not script.exists():
        ui.fail("launcher/build_exe.bat fehlt.")
        return False
    ui.info("Baue Jarvis.exe — das kann ein paar Minuten dauern …")
    with ui.spinner("PyInstaller läuft") as spinner:
        result = subprocess.run(["cmd", "/c", str(script)], cwd=str(PROJECT_DIR),
                                capture_output=True, text=True, timeout=1800,
                                errors="replace")
        spinner.update("Aufräumen")
    if result.returncode == 0:
        ui.ok(f"Fertig: {PROJECT_DIR / 'dist' / 'Jarvis.exe'}")
        return True
    ui.fail("Build fehlgeschlagen — die letzten Zeilen:")
    ui.lines("\n".join((result.stdout or result.stderr or "").splitlines()[-15:]))
    return False


def open_folder() -> None:
    target = ctx.ROOT
    if ctx.IS_WINDOWS:
        os.startfile(str(target))  # noqa: S606 - opening Explorer is the point
    else:
        subprocess.run(["open", str(target)] if ctx.IS_MACOS else ["xdg-open", str(target)])
    ui.ok(f"Projektordner geöffnet: {target}")
