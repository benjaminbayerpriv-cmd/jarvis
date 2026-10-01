"""Where Jarvis lives on disk and how its configuration is stored.

Shared by every CLI command: project root discovery, the .venv interpreter,
the .env file (read/modify/write without losing the user's comments) and the
.jarvis/ state directory holding pid files and log files.

Only the standard library — this module is imported before anything is
installed, i.e. in exactly the state a fresh ZIP is in.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".jarvis"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
SERVER_PID = STATE_DIR / "server.pid"
HOTKEY_PID = STATE_DIR / "hotkey.pid"
SERVER_LOG = STATE_DIR / "server.log"
HOTKEY_LOG = STATE_DIR / "hotkey.log"

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"

# A bare id in .env: keys in .env.example that still hold a "your-…-key"
# placeholder count as unset. The backend treats any non-empty value as
# configured, so a .env copied verbatim from the example would silently
# activate DeepSeek and its billing against a bogus key.
_PLACEHOLDER = re.compile(r"^\s*(your[-_].*|changeme|xxx+|todo|<.*>)\s*$", re.IGNORECASE)


def ensure_state_dir() -> Path:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        return STATE_DIR
    except OSError:
        return Path(os.environ.get("TEMP", ".")) / "jarvis-cli"


# --------------------------------------------------------------------- .env
def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env(key: str, default: str = "") -> str:
    value = read_env().get(key, default)
    return "" if _PLACEHOLDER.match(value or "") else value


def env_present(key: str) -> bool:
    return key in read_env()


def write_env(updates: dict[str, str]) -> None:
    """Set the given keys in .env, keeping every other line (including
    comments) byte-for-byte. New keys are appended in a block at the end."""
    path = ENV_FILE
    if not path.exists():
        header = "# Jarvis — von der CLI (jarvis setup) erzeugt. Kommentare beginnen mit #."
        body = [header]
        if ENV_EXAMPLE.exists():
            for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    _, _, value = line.partition("=")
                    if _PLACEHOLDER.match(value.strip()):
                        line = f"{line.partition('=')[0].strip()}="
                body.append(line)
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for key, value in updates.items():
        entry = f"{key}={value}"
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = entry
                break
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def secret(value: str, keep: int = 4) -> str:
    value = (value or "").strip()
    if not value:
        return "—"
    return f"{value[:keep]}…{value[-keep:]} ({len(value)} Zeichen)" if len(value) > keep * 2 + 2 else "•" * len(value)


# ------------------------------------------------------------------ python
def venv_python() -> Path | None:
    candidate = ROOT / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python3")
    return candidate if candidate.exists() else None


def backend_python() -> Path | None:
    """Interpreter able to run backend.main: the venv if it exists, else the
    interpreter running the CLI only if its dependencies are importable."""
    venv = venv_python()
    if venv:
        return venv
    if sys.prefix != sys.base_prefix or _deps_importable(sys.executable):
        return Path(sys.executable)
    return None


def _deps_importable(python: str) -> bool:
    return subprocess.run(
        [python, "-c", "import fastapi, uvicorn, mcp, requests, dotenv"],
        capture_output=True, creationflags=no_window(),
    ).returncode == 0


REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "requests": "requests",
    "dotenv": "python-dotenv",
    "mcp": "mcp (Werkzeuge fürs Modell)",
    "pynput": "pynput (Hotkey)",
    "supertonic": "supertonic (Stimme)",
    "faster_whisper": "faster-whisper (Spracherkennung)",
    "send2trash": "send2trash (Papierkorb)",
    "num2words": "num2words",
    "webview": "pywebview (App-Fenster)",
    "anyio": "anyio",
}


def missing_modules(python: Path | None = None) -> list[str]:
    """Which requirements aren't importable in the given interpreter — the
    first thing to know when a fresh install misbehaves."""
    interpreter = str(python or venv_python() or sys.executable)
    if not Path(interpreter).exists():
        return list(REQUIRED_MODULES.values())
    probe = "import importlib.util,sys;" + ";".join(
        f"print('{name}', 0 if importlib.util.find_spec('{name}') else 1)" for name in REQUIRED_MODULES
    ) + ";sys.exit(0)"
    try:
        out = subprocess.run([interpreter, "-c", probe], capture_output=True, text=True,
                             timeout=120, errors="replace",
                             creationflags=no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return ["(pip-Status unbekannt)"]
    missing, probed = [], 0
    for line in out.splitlines():
        name, _, flag = line.partition(" ")
        if name not in REQUIRED_MODULES:
            continue
        probed += 1
        if flag.strip() == "1":
            missing.append(REQUIRED_MODULES[name])
    if probed < len(REQUIRED_MODULES):
        # The interpreter didn't run the probe (e.g. a .venv whose base Python
        # was removed) — silence must not read as "everything installed".
        return ["(pip-Status unbekannt)"]
    return missing


def deps_ok() -> bool:
    return not missing_modules()


def no_window() -> int:
    return 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def venv_python_version() -> tuple[int, int, int] | None:
    python = venv_python()
    if not python:
        return None
    try:
        out = subprocess.run([str(python), "--version"], capture_output=True, text=True,
                             timeout=20, errors="replace",
                             creationflags=no_window()).stdout
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    except (OSError, subprocess.SubprocessError):
        return None
    return (int(match[1]), int(match[2]), int(match[3] or 0)) if match else None


def system_python_ok() -> bool:
    return sys.version_info >= (3, 10)


# ----------------------------------------------------------------- process
def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, errors="replace",
                             creationflags=no_window()).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def write_pid(path: Path, pid: int) -> None:
    ensure_state_dir()
    path.write_text(str(pid), encoding="utf-8")


def stop_pid(pid: int, label: str = "Prozess") -> bool:
    if not process_alive(pid):
        return False
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=no_window())
    else:
        for sig, wait in ((signal.SIGTERM, 6.0), (signal.SIGKILL, 3.0)):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return True
            deadline = time.time() + wait
            while time.time() < deadline:
                if not process_alive(pid):
                    return True
                time.sleep(0.15)
    return not process_alive(pid)


def run_hidden(args: list[str], log: Path | None = None, cwd: Path | None = None) -> subprocess.Popen | None:
    """Start a detached background process, optionally appending its output to
    a log file. Returns None when the executable doesn't exist."""
    if not args or not Path(args[0]).exists():
        return None
    ensure_state_dir()
    stream = open(log, "a", encoding="utf-8", errors="replace") if log else subprocess.DEVNULL
    if log:
        stream.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)} ===\n")
        stream.flush()
    creationflags = 0
    if IS_WINDOWS:
        creationflags = 0x00000008 | 0x00000200 | no_window()  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    kwargs: dict = {}
    if not IS_WINDOWS:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(
            args, cwd=str(cwd or ROOT), stdout=stream, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=creationflags, **kwargs,
        )
    except OSError:
        return None


def tail(path: Path, lines: int = 40) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


# -------------------------------------------------------------------- http
def http_json(url: str, timeout: float = 5.0, headers: dict | None = None, method: str = "GET",
              body: dict | None = None):
    """(payload, None) on success, (None, human-readable error) otherwise —
    every caller in the CLI wants to print a message, not traceback."""
    import json as _json

    data = _json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        return (_json.loads(raw or b"null"), None)
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 401:
            hint = " — LM Studio verlangt ein Token (Require Authentication)"
        elif exc.code == 404:
            hint = " — Endpoint gibt es nicht (ältere LM-Studio-Version?)"
        return None, f"HTTP {exc.code}{hint}"
    except urllib.error.URLError as exc:
        return None, f"nicht erreichbar ({exc.reason})"
    except TimeoutError:
        return None, "Zeitüberschreitung"
    except (OSError, http.client.HTTPException) as exc:
        # getresponse() errors (server reset/closed the connection mid-request)
        # are not wrapped in URLError by urllib.
        return None, f"Verbindung abgebrochen ({exc.__class__.__name__})"
    except ValueError:
        return None, "ungültige Antwort"


def open_url(url: str) -> bool:
    try:
        import webbrowser

        return webbrowser.open(url)
    except Exception:
        return False


def local_ip() -> str:
    """This machine's LAN-facing IPv4 (UDP connect picks the route without
    sending anything) — the address another machine has to reach Jarvis on."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        probe.close()


def which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None
