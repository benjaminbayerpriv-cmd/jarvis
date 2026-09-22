"""PTY bridge for the real OpenCode TUI in the JARVIS Code-Tab.

The Code-Tab opens the actual OpenCode terminal UI (`opencode <dir>`) inside an
embedded xterm.js terminal — not a custom chat view. The browser attaches to
`/code/tty/ws`; the server spawns opencode on an xterm-256color PTY and streams
raw bytes both ways (PTY→WS as binary frames, WS→PTY for keystrokes) plus
terminal resizes and exit handling.

Why a PTY: opencode's TUI is an interactive OpenTUI app. It needs a real tty to
render the alternate screen, capture the mouse and handle bracketed paste, and
it line-buffers when piped. Streaming the child's stdout through a
pseudo-terminal yields the exact bytes the TUI would emit on a real terminal.

The one thing this module keeps from the earlier headless approach is the LM
Studio wiring: the TUI must know about the local models, so before it starts we
merge an `lmstudio` provider into ~/.config/opencode/opencode.json (preserving
the user's other providers) and point opencode at the off-`PROVIDER_ID` model
that can actually run it (see CODE_MIN_CONTEXT) so it does not start on a model
whose loaded context is too small.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import signal
import sqlite3
import struct
import subprocess
import threading
import time

try:
    # POSIX-only — the real OpenCode TUI needs an actual PTY (openpty,
    # TIOCSWINSZ, process-group signalling); Windows has no equivalent in the
    # stdlib. Falling back to None here instead of letting the import crash
    # keeps the rest of the app (voice, chat, vision, everything not
    # Code-Tab) working on Windows — start_tty() below raises the real
    # limitation only when someone actually opens the Code-Tab, instead of
    # every startup dying at import time.
    import fcntl
    import pty
    import termios
except ImportError:
    fcntl = None
    pty = None
    termios = None

# Windows: unter ConPTY (pywinpty) gibt es keinen POSIX-PTY-fd, daher fährt der
# Code-Tab dort eine PtyProcess. Der Import gelingt nur unter Windows; auf
# POSIX (macOS/Linux) bleibt er None und der gewohnte openpty-Pfad läuft.
WIN = os.name == "nt"
try:
    if WIN:
        from winpty import PtyProcess
    else:
        PtyProcess = None
except ImportError:
    PtyProcess = None

from . import config

# JARVIS Code: eigene opencode-Binary (Rebrand), gebaut aus dem
# `opencode`-Submodule (siehe .gitmodules) unter releases/ im Repo-Root.
# Per Env überschreibbar: OPENCODE_BIN=/pfad/zum/binary
_RELEASES_DIR = config.ROOT_DIR / "opencode" / "releases"
if os.name == "nt":
    _JARVIS_CODE_BIN = str(_RELEASES_DIR / "jarvis-code-windows-x64.exe")
else:
    _arch = "arm64" if os.uname().machine == "arm64" else "x64"
    _JARVIS_CODE_BIN = str(_RELEASES_DIR / f"jarvis-code-darwin-{_arch}")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", _JARVIS_CODE_BIN)

# Claude Code and Codex are both installed by the user themselves (`npm i -g
# @anthropic-ai/claude-code` / `npm i -g @openai/codex`) and picked up from
# PATH — unlike the bundled jarvis-code binary above, JARVIS does not ship or
# configure them. Both authenticate and pick their own model on their own
# (claude login / codex login, or an API key in their own config), so unlike
# opencode there is no LM Studio provider wiring to merge in for them.
#
# shutil.which() alone only sees $PATH — fine from a terminal, but the
# packaged app (launcher/jarvis_launcher.py) is started by double-clicking
# it or from the Dock, and macOS then hands the process launchd's minimal
# default PATH (/usr/bin:/bin:/usr/sbin:/sbin, no ~/.local/bin), not the
# shell's. Both CLIs are typically npm-global-installed under one of a
# handful of well-known directories, so probe those directly as a fallback
# before giving up and falling back to the bare name.
_EXTRA_BIN_DIRS = [
    pathlib.Path.home() / ".local" / "bin",
    pathlib.Path.home() / ".npm-global" / "bin",
    pathlib.Path.home() / ".bun" / "bin",
    pathlib.Path("/opt/homebrew/bin"),
    pathlib.Path("/usr/local/bin"),
]


def _find_bin(name: str, env_var: str) -> str:
    override = os.environ.get(env_var)
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    for d in _EXTRA_BIN_DIRS:
        candidate = d / name
        if candidate.exists():
            return str(candidate)
    return name


CLAUDE_BIN = _find_bin("claude", "CLAUDE_BIN")
CODEX_BIN = _find_bin("codex", "CODEX_BIN")

# The coding agents the Code-Tab / voice mode can drive in the PTY terminal.
# "opencode" stays the default (existing behaviour); the other two are
# switched to via set_code_agent() (see backend/tools.py's set_code_agent
# voice tool).
CODE_AGENTS: dict[str, str] = {
    "opencode": "OpenCode",
    "claude": "Claude Code",
    "codex": "Codex",
}


def agent_bin(agent_id: str) -> str:
    return {"opencode": OPENCODE_BIN, "claude": CLAUDE_BIN, "codex": CODEX_BIN}.get(agent_id, "")


def agent_available(agent_id: str) -> bool:
    """Whether the agent's binary can actually be launched.

    opencode ships its own binary under releases/ (checked by path); claude
    and codex are resolved from PATH at import time, so "available" there
    just means shutil.which found something.
    """
    b = agent_bin(agent_id)
    if not b:
        return False
    if agent_id == "opencode":
        return pathlib.Path(b).exists()
    return shutil.which(b) is not None or pathlib.Path(b).exists()


def list_code_agents() -> list[dict]:
    return [{"id": aid, "name": name, "available": agent_available(aid)} for aid, name in CODE_AGENTS.items()]


def get_code_agent() -> str:
    """The coding agent currently selected for the Code-Tab / voice terminal."""
    agent = str(config.load_config().get("code_agent", "")).strip()
    return agent if agent in CODE_AGENTS else "opencode"


def set_code_agent(agent_id: str) -> None:
    if agent_id not in CODE_AGENTS:
        raise ValueError(f"Unbekannter Coding-Agent: {agent_id!r}")
    cfg = config.load_config()
    cfg["code_agent"] = agent_id
    config.CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_agent(name: str) -> str | None:
    """Findet zu einer gesprochenen Bezeichnung ("Claude Code", "Codex",
    "OpenCode") die Agent-Id — genauso tolerant wie resolve_model() oben,
    weil die Spracherkennung Groß-/Kleinschreibung und Leerzeichen frei
    erfindet ("claude code" vs. "Claude-Code")."""
    wanted = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
    if not wanted:
        return None
    if "codex" in wanted:
        return "codex"
    if "claude" in wanted:
        return "claude"
    if "opencode" in wanted or "open" in wanted:
        return "opencode"
    return None


# Where opencode reads its provider config. We MERGE into it, never overwrite.
OPENCODE_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"

# opencode's system prompt + tools needs roughly this many context tokens.
CODE_MIN_CONTEXT = 24000

# Default working directory for the code agent (overridable via the settings UI).
DEFAULT_CODE_DIR = os.path.expanduser("~/Developer")

# opencode's bundled provider id for our custom OpenAI-compatible provider.
PROVIDER_ID = "lmstudio"

# opencode's own SQLite session store (separate from JARVIS's own conversations
# under backend/conversations/) - lets the Code-Tab sidebar show opencode's
# real sessions instead of JARVIS chat conversations that were never meant for it.
if WIN:
    OPENCODE_DB = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "opencode" / "opencode.db"
else:
    OPENCODE_DB = pathlib.Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def list_recent_sessions(directory: str | None = None, limit: int = 40) -> list[dict]:
    """Real opencode sessions (title, directory, last-updated) from opencode's
    own SQLite DB — read-only, best-effort. Returns [] if opencode has never
    run or its storage format changed rather than raising, since this only
    feeds an optional sidebar list."""
    if not OPENCODE_DB.exists():
        return []
    try:
        uri = f"file:{OPENCODE_DB}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            con.row_factory = sqlite3.Row
            if directory:
                rows = con.execute(
                    "SELECT id, title, directory, time_created, time_updated FROM session "
                    "WHERE directory = ? AND parent_id IS NULL ORDER BY time_updated DESC LIMIT ?",
                    (directory, limit),
                ).fetchall()
                if not rows:
                    rows = con.execute(
                        "SELECT id, title, directory, time_created, time_updated FROM session "
                        "WHERE parent_id IS NULL ORDER BY time_updated DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, title, directory, time_created, time_updated FROM session "
                    "WHERE parent_id IS NULL ORDER BY time_updated DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception:
        return []


def delete_session(session_id: str) -> bool:
    """Delete a real opencode session via opencode's own CLI (``opencode session
    delete <id>``) rather than touching its SQLite store directly, so opencode's
    own cleanup (messages, snapshots, session_diff) runs correctly."""
    if not session_id:
        return False
    try:
        result = subprocess.run(
            [OPENCODE_BIN, "session", "delete", session_id],
            capture_output=True,
            timeout=15,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def rename_session(session_id: str, title: str) -> bool:
    """Rename a real opencode session. opencode's CLI has no ``session rename``
    subcommand, so this updates the ``title`` column directly in opencode's
    own SQLite store (WAL mode, so this is safe alongside a running opencode
    process — it just won't see the new title until its next query)."""
    if not session_id or not title:
        return False
    if not OPENCODE_DB.exists():
        return False
    try:
        con = sqlite3.connect(str(OPENCODE_DB), timeout=5)
        try:
            cur = con.execute(
                "UPDATE session SET title = ?, time_updated = ? WHERE id = ?",
                (title, int(time.time() * 1000), session_id),
            )
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()
    except Exception:
        return False


def _lmstudio_host() -> str:
    """Derive the LM Studio internal-API origin from the chat base URL.

    config.LM_STUDIO_BASE_URL is e.g. http://localhost:1234/v1 (OpenAI-style).
    The internal /api/v0/models endpoint (which reports context lengths) lives
    on the same origin but WITHOUT the /v1 suffix.
    """
    url = config.LM_STUDIO_BASE_URL.rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


def list_models() -> list[dict]:
    """Every non-embedding LM Studio model, with its loaded/max context.

    Returns a list of ``{id, loaded_context, max_context, state}``. ``state``
    is ``"loaded"`` or ``"not-loaded"``; ``loaded_context`` is 0 for models not
    currently in memory (the UI can then fall back to ``max_context`` and warn
    that the model must be loaded with a big enough context).
    """
    try:
        import requests

        resp = requests.get(f"{_lmstudio_host()}/api/v0/models", timeout=5)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as exc:  # noqa: BLE001 - report as empty, UI shows a hint
        print(f"[code] LM-Studio-Modelle nicht abrufbar: {exc}")
        return []

    out = []
    for m in data:
        mid = m.get("id", "")
        if not mid or "embed" in mid.lower():
            continue
        out.append(
            {
                "id": mid,
                "loaded_context": int(m.get("loaded_context_length") or 0),
                "max_context": int(m.get("max_context_length") or 0),
                "state": m.get("state", "not-loaded"),
            }
        )
    # Loaded models first, then big-context models first (opencode needs a lot
    # of context; see the module docstring).
    out.sort(
        key=lambda m: (
            (0 if m["state"] == "loaded" else 1),
            -(m.get("loaded_context") or m.get("max_context") or 0),
        )
    )
    return out


def current_model() -> str:
    """The model currently selected in the JARVIS model picker."""
    return config.LM_STUDIO_MODEL


# Mitschnitt der TUI-Ausgabe. Jarvis schickt Aufträge an opencode, konnte
# bisher aber nicht sehen, was dabei herauskommt — auf "wie weit ist er?"
# blieb ihm nur Raten (und der Ehrlichkeits-Filter machte daraus zu Recht
# "das habe ich nicht ausgeführt"). Der WebSocket-Pump in main.py reicht
# jeden Block hier durch; opencode_status() liest das Ende wieder aus.
_OUTPUT_LIMIT = 60000
_output_lock = threading.Lock()
_output_buf: list[str] = []


def note_output(data: bytes) -> None:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - Mitschnitt darf den PTY nie stören
        return
    with _output_lock:
        _output_buf.append(text)
        total = sum(len(p) for p in _output_buf)
        while total > _OUTPUT_LIMIT and len(_output_buf) > 1:
            total -= len(_output_buf.pop(0))
    _check_state()


def reset_output() -> None:
    global _state, _state_checked_at
    with _output_lock:
        _output_buf.clear()
    _state = "idle"
    _state_checked_at = 0.0


# Zustandswechsel der TUI melden, damit Jarvis von sich aus Bescheid sagen
# kann — sonst merkt der Nutzer nie, dass opencode auf eine Antwort wartet
# oder längst fertig ist (er sieht das Terminal ja nicht zwangsläufig an).
_state = "idle"          # idle | busy | permission
_state_checked_at = 0.0
_STATE_MIN_INTERVAL = 0.5


def _check_state() -> None:
    global _state, _state_checked_at
    now = time.monotonic()
    # Die TUI zeichnet bei jedem Tastendruck komplett neu; ohne Drossel
    # liefe die Auswertung hunderte Male pro Sekunde.
    if now - _state_checked_at < _STATE_MIN_INTERVAL:
        return
    _state_checked_at = now
    # Bewusst nur ein kurzes Stück: die TUI zeichnet ihren ganzen Bildschirm
    # bei jeder Änderung neu, und in einem längeren Ausschnitt steht das
    # "esc interrupt" vergangener Neuzeichnungen noch drin — der Zustand
    # bliebe dann für immer auf "beschäftigt" (live beobachtet: die
    # Fertig-Meldung kam nie).
    screen = recent_output(600).lower()
    if not screen:
        return
    # Diese drei Muster sind aus OpenCodes eigener TUI (OpenTUI) abgelesen —
    # "live beobachtet", nicht dokumentiert. Claude Code und Codex haben eine
    # andere Oberfläche mit anderem Wortlaut; bei ihnen läuft dieselbe
    # Erkennung mangels passender Muster einfach leer mit (keine Meldungen),
    # statt etwas Falsches zu behaupten — kein aktiver Fehler, nur eine
    # Lücke, die bislang niemand gegen die echten CLIs verifiziert hat.
    if "has crashed" in screen:
        new_state = "crashed"
    elif "permission required" in screen:
        new_state = "permission"
    elif "esc interrupt" in screen:
        new_state = "busy"
    else:
        new_state = "idle"
    if new_state == _state:
        return
    previous, _state = _state, new_state
    name = CODE_AGENTS.get(get_code_agent(), "Der Coding-Agent")
    if new_state == "permission":
        _announce(f"{name} braucht eine Freigabe und wartet auf dich.")
    elif new_state == "crashed":
        _announce(f"{name} ist abgestürzt.")
    elif new_state == "idle" and previous in ("busy", "permission"):
        _announce(f"{name} ist fertig.")


def _announce(text: str) -> None:
    # Spät importiert: panel importiert transcript_log, und ein Import ganz
    # oben würde den Modulkreis schließen.
    from . import panel

    panel.push("opencode_event", text=text)


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[\]P][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]")


def recent_output(max_chars: int = 2000) -> str:
    """Die letzten lesbaren Zeilen der TUI — ohne Steuerzeichen und ohne die
    Rahmen-/Füllzeichen, mit denen die Oberfläche ihr Layout malt."""
    with _output_lock:
        raw = "".join(_output_buf)
    if not raw:
        return ""
    plain = _ANSI_RE.sub("", raw).replace("\r", "\n")
    lines = []
    for ln in plain.split("\n"):
        ln = "".join(ch for ch in ln if ch == "\t" or ch >= " ")
        ln = ln.replace("█", " ").strip(" ─│┌┐└┘░▒▓")
        if ln.strip():
            lines.append(ln.rstrip())
    # Aufeinanderfolgende Dubletten: die TUI zeichnet denselben Bildschirm
    # bei jedem Tastendruck neu, sonst steht alles zigfach da.
    deduped = [ln for i, ln in enumerate(lines) if i == 0 or ln != lines[i - 1]]
    return "\n".join(deduped)[-max_chars:]


def list_all_models() -> list[str]:
    """Alle Modelle, die opencode kennt — als vollständige IDs inklusive
    Provider ("lmstudio/qwen/qwen3.5-9b", "opencode/big-pickle").

    Bewusst über `opencode models` statt über LM Studio: opencode bringt
    eigene (auch kostenlose) Modelle mit, die LM Studio gar nicht kennt und
    die sonst nicht auswählbar wären.
    """
    try:
        out = subprocess.run(
            [OPENCODE_BIN, "models"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in out.splitlines() if "/" in ln and not ln.startswith(" ")]


def get_selected_model() -> str:
    """Das ausdrücklich für opencode gewählte Modell (z.B. per Sprachbefehl),
    oder "" wenn noch keins gesetzt wurde."""
    return str(config.load_config().get("code_model", "")).strip()


def set_selected_model(model_id: str) -> None:
    cfg = config.load_config()
    cfg["code_model"] = model_id
    config.CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_model(name: str, available: list[str] | None = None) -> str | None:
    """Findet zu einer gesprochenen Bezeichnung ("das GPT OSS", "Big Pickle",
    "qwen coder") die vollständige Modell-ID. Gesucht wird stur über
    Wortteile, weil die Spracherkennung Bindestriche, Punkte und
    Großschreibung frei erfindet."""
    wanted = [w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if len(w) > 1]
    if not wanted:
        return None
    best, best_score = None, 0
    # Die Liste kostet einen Prozessstart — wer sie schon hat, reicht sie
    # durch, statt die Binary ein zweites Mal zu befragen.
    for full_id in (available if available is not None else list_all_models()):
        hay = re.split(r"[^a-z0-9]+", full_id.lower())
        score = sum(1 for w in wanted if any(w in part or part in w for part in hay))
        if score > best_score:
            best, best_score = full_id, score
    return best


def default_model() -> str:
    """Best default for opencode: a loaded model whose context fits opencode.

    Prefers a loaded coder model with enough context, then any loaded model
    with enough context, else falls back to a known-good default. The JARVIS
    chat model is deliberately NOT chosen unconditionally: qwen3.5-9b loads
    with 8192 context and cannot run opencode's ~20k-token system prompt.
    """
    models = list_models()
    # Eine ausdrückliche Wahl schlägt die Heuristik — sonst würde sie beim
    # nächsten Start des Terminals still wieder überschrieben.
    picked = get_selected_model()
    if picked and any(m["id"] == picked for m in models):
        return picked
    enough = [m for m in models if m.get("loaded_context", 0) >= CODE_MIN_CONTEXT]
    if not enough:
        return "google/gemma-4-e4b"
    # Honoriere das im JARVIS-Picker gewählte Modell, wenn es opencode packt;
    # sonst ein Coder-Modell, sonst das mit dem größten Kontext.
    chosen = config.LM_STUDIO_MODEL
    for m in enough:
        if m["id"] == chosen:
            return chosen
    coders = [m for m in enough if "coder" in m["id"].lower()]
    return (coders[0]["id"] if coders else enough[0]["id"])


def startup_model() -> str:
    """Vollständige Modell-ID, mit der die TUI starten soll — die
    ausdrückliche Wahl, sonst die Heuristik aus default_model()."""
    picked = get_selected_model()
    if picked:
        if picked.startswith(PROVIDER_ID + "/"):
            return picked
        # Ältere gespeicherte Werte waren reine LM-Studio-IDs ohne Provider;
        # alles andere (z.B. "opencode/big-pickle") ist bereits vollständig.
        if any(m["id"] == picked for m in list_models()):
            return f"{PROVIDER_ID}/{picked}"
        return picked
    fallback = default_model()
    return f"{PROVIDER_ID}/{fallback}" if fallback else ""


def get_code_dir() -> str:
    cfg = config.load_config()
    d = str(cfg.get("code_dir", "")).strip() or DEFAULT_CODE_DIR
    d = os.path.expanduser(d)
    p = pathlib.Path(d)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return str(pathlib.Path.home())
    return str(p)


def set_code_dir(dir_path: str) -> None:
    cfg = config.load_config()
    cfg["code_dir"] = dir_path
    config.CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_provider_config(models: list[dict], model_id: str) -> dict:
    """Merge an ``lmstudio`` provider into the opencode config.

    Preserves every existing key (the user's ``ollama-lan`` provider, etc.).
    Writes a one-time ``.bak`` the first time. Returns the merged config.
    """
    cfg = {}
    if OPENCODE_CONFIG.exists():
        cfg = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    # Only back up once, so repeated UI opens don't churn .bak files.
    bak = pathlib.Path(str(OPENCODE_CONFIG) + ".jarvis.bak")
    if not bak.exists():
        if OPENCODE_CONFIG.exists():
            bak.write_text(OPENCODE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    cfg["provider"] = cfg.get("provider", {})
    cfg["provider"][PROVIDER_ID] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "LM Studio (local)",
        "options": {"baseURL": config.LM_STUDIO_BASE_URL, "apiKey": "lm-studio"},
        "models": {m["id"]: {"name": m["id"]} for m in models},
    }
    # model_id ist eine vollständige ID inklusive Provider — auch ein Modell
    # von opencode selbst (z.B. "opencode/big-pickle") muss hier stehen
    # können, nicht nur eins aus LM Studio.
    cfg["model"] = model_id
    OPENCODE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OPENCODE_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cfg


class TtyHandle:
    """Plattform-Abstraktion über den Code-Tab-Prozess.

    Der WebSocket-Handler in main.py spricht nur noch mit diesem Objekt
    (``read``/``write``/``resize``/``kill``/``close``/``poll``) und kümmert
    sich nicht um die Plattform. Unter macOS/Linux kapselt es einen echten
    PTY-master-fd (openpty + Prozessgruppe); unter Windows eine pywinpty
    :class:`PtyProcess` (ConPTY), die keinen fd hat — dort laufen read/write
    über den ConPTY-Kanal und erwarten bzw. liefern Text, der hier auf Bytes
    umgemappt wird.
    """

    def __init__(self) -> None:
        self.platform = "posix"
        self.master: int | None = None
        self.proc: subprocess.Popen | None = None
        self.winpty = None  # pywinpty PtyProcess (nur Windows)

    @classmethod
    def posix(cls, master: int, proc: subprocess.Popen) -> "TtyHandle":
        h = cls()
        h.platform = "posix"
        h.master = master
        h.proc = proc
        return h

    @classmethod
    def windows(cls, winpty_proc) -> "TtyHandle":
        h = cls()
        h.platform = "windows"
        h.winpty = winpty_proc
        h.proc = winpty_proc
        return h

    def read(self, n: int = 65536) -> bytes:
        """Raw-Ausgabe als Bytes. Gibt ``b""`` bei EOF zurück."""
        if self.platform == "windows":
            try:
                s = self.winpty.read(n)
            except EOFError:
                return b""
            return (s or "").encode("utf-8", errors="replace")
        return os.read(self.master, n)

    def write(self, data: bytes) -> None:
        """Tastendruck-/Byte-Strom in den Prozess stdin."""
        if self.platform == "windows":
            self.winpty.write(data.decode("utf-8", errors="replace"))
            return
        os.write(self.master, data)

    def resize(self, cols: int, rows: int) -> None:
        """Teile dem Terminal die neue Größe mit und nudge zum Reflow."""
        if self.platform == "windows":
            self.winpty.setwinsize(rows, cols)
            return
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            return
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGWINCH)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def kill(self, grace: float = 2.0) -> None:
        """Prozess beenden — Windows via ConPTY, POSIX als Prozessgruppe."""
        if self.platform == "windows":
            try:
                self.winpty.terminate(force=True)
            except Exception:  # noqa: BLE001 - best effort
                pass
            return
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(grace)
        except subprocess.TimeoutExpired:
            if self.proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    self.proc.kill()
                try:
                    self.proc.wait()
                except Exception:  # noqa: BLE001 - best-effort reap
                    pass

    def close(self) -> None:
        """Gebe den PTY-fd frei (no-op auf Windows, ConPTY hat keinen fd)."""
        if self.platform == "windows":
            return
        try:
            os.close(self.master)
        except OSError:
            pass
        self.master = None

    def poll(self) -> int | None:
        """Exit-Code, oder None solange der Prozess noch läuft."""
        if self.platform == "windows":
            return None if self.winpty.isalive() else 0
        return self.proc.poll()


def _build_cmd(agent_id: str, workdir: str, session_id: str | None) -> list[str]:
    """Baut die Startkommandozeile für den gewählten Coding-Agenten.

    opencode braucht das Arbeitsverzeichnis als Argument und eine eigene
    LM-Studio-Provider-Konfiguration (siehe ensure_provider_config); Claude
    Code und Codex laufen dagegen einfach im PTY-cwd (siehe subprocess.Popen/
    PtyProcess.spawn unten) und bringen ihre eigene Modell-/Auth-Konfiguration
    mit — dafür gibt es hier nichts zu wiring.
    """
    if agent_id == "claude":
        cmd = [CLAUDE_BIN]
        if session_id:
            # --resume <id> setzt eine konkrete, zuvor geführte Sitzung fort
            # (siehe https://code.claude.com/docs/en/sessions).
            cmd += ["--resume", session_id]
        return cmd

    if agent_id == "codex":
        cmd = [CODEX_BIN]
        if session_id:
            # "resume <id>" ist bei Codex ein Subcommand, kein Flag.
            cmd += ["resume", session_id]
        return cmd

    # opencode (Standard)
    models = list_models()
    wanted = startup_model()
    if models:
        ensure_provider_config(models, wanted)
    cmd = [OPENCODE_BIN, workdir]
    if session_id:
        cmd += ["--session", session_id]
    # Das "model" aus der Konfiguration ist für opencode nur der Startwert für
    # NEUE Sitzungen — es merkt sich daneben das zuletzt benutzte Modell und
    # startete damit weiter, obwohl die Konfiguration längst ein anderes nannte
    # (live gesehen: Konfiguration devstral, TUI lief mit gpt-oss). --model
    # setzt es für diesen Start verbindlich.
    # wanted ist bereits vollständig (Provider inklusive, siehe startup_model)
    # — hier NICHT noch einmal präfixen, sonst startet die TUI mit
    # "lmstudio/lmstudio/…", verwirft die unbekannte ID stillschweigend und
    # nimmt ihr gemerktes Modell (live beobachtet).
    if wanted:
        cmd += ["--model", wanted]
    return cmd


def start_tty(workdir: str, session_id: str | None = None) -> TtyHandle:
    """Starte die TUI des aktuell gewählten Coding-Agenten (siehe
    get_code_agent()/set_code_agent()) in einem PTY/ConPTY; gib einen
    TtyHandle zurück.

    Bei opencode wird zuerst die Provider-Konfiguration aktualisiert, damit
    die TUI die LM-Studio-Modelle sieht (siehe _build_cmd). Claude Code und
    Codex laufen unverändert mit ihrer eigenen Konfiguration. Auf POSIX läuft
    der Kindprozess in einer eigenen Session (Prozessgruppe → per
    SIGTERM/SIGWINCH steuerbar); auf Windows übernimmt eine
    pywinpty-PtyProcess (ConPTY). Der Aufrufer besitzt das Handle und erklärt
    sich bereit, es am Ende zu schließen/abzuräumen.

    session_id: wenn gesetzt, wird die TUI mit einer echten, zuvor per
    list_recent_sessions() gefundenen Session fortgesetzt statt einer neuen.
    """
    agent_id = get_code_agent()
    if not agent_available(agent_id):
        name = CODE_AGENTS.get(agent_id, agent_id)
        raise RuntimeError(
            f"{name} ist nicht installiert oder nicht im PATH gefunden "
            f"({agent_bin(agent_id)!r}). Bitte installieren und erneut versuchen."
        )

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    # Same reasoning as _find_bin() above: the packaged app's PATH may lack
    # the directories these CLIs (or tools they shell out to, e.g. git/node)
    # live in. Appending rather than replacing keeps whatever PATH the
    # process already had.
    existing_path = env.get("PATH", "")
    extra = [str(d) for d in _EXTRA_BIN_DIRS if str(d) not in existing_path]
    if extra:
        env["PATH"] = os.pathsep.join([existing_path, *extra]) if existing_path else os.pathsep.join(extra)

    cmd = _build_cmd(agent_id, workdir, session_id)

    if WIN:
        if PtyProcess is None:
            raise RuntimeError("pywinpty ist nicht installiert – bitte `pip install pywinpty` ausführen, um den Code-Tab auf Windows zu nutzen.")
        wp = PtyProcess.spawn(
            cmd,
            cwd=workdir or None,
            env=env,
            dimensions=(24, 120),  # rows, cols
        )
        return TtyHandle.windows(wp)

    if pty is None:
        raise RuntimeError("Code-Tab erfordert ein PTY, das auf diesem System nicht verfügbar ist.")

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=workdir or None,
        start_new_session=True,
    )
    os.close(slave)  # child owns the slave; we keep only the master.
    return TtyHandle.posix(master, proc)


def resize_tty(tty: TtyHandle, cols: int, rows: int) -> None:
    """Größenänderung an das TtyHandle durchreichen (POSIX: TIOCSWINSZ+SIGWINCH)."""
    tty.resize(cols, rows)


def answer_terminal_queries(tty: TtyHandle, data: bytes, state: dict) -> None:
    r"""Beantworte OpenTUI-Terminalanfragen, die xterm.js nicht abdeckt.

    Die opencode-TUI (OpenTUI) prüft das Terminal und blockiert, bis sie eine
    Antwort auf drei Anfragen bekommt, die xterm.js offen lässt (DSR, DECRQM,
    DA1 und OSC 10/11 beantwortet es selbst über seinen ``onData``-Hook):

      - ``ESC[>0q``           DA2, sekundäre Geräteattribute
      - ``ESC P + q <hex> ESC \``  XTGETTCAP, Terminfo-Stringabfrage
      - ``ESC[14t``           XTREPORTWIN, Fenstergröße in Pixeln

    Wir halten in ``state`` einen kurzen Rolling-Buffer, damit eine über zwei
    ``read``-Aufrufe verteilte Anfrage trotzdem erkannt wird, und schreiben die
    Antwort dann direkt ins TtyHandle (so wie es ein echter Terminalemulator
    tun würde).
    """
    buf = state.get("term_buf", b"") + data
    state["term_buf"] = buf[-512:]
    cols = int(state.get("cols", 80))
    rows = int(state.get("rows", 24))
    answers: list[bytes] = []

    if b"\x1b[>0q" in buf:
        answers.append(b"\x1b[>1;276;0c")  # xterm-like, 256 Farben, DA2-Antwort

    for m in re.finditer(rb"\x1bP\+q([0-9A-Za-z]+)\x1b\\", buf):
        # Gemeldete Terminfo-Strings als nicht unterstützt (leerer Wert) deklarieren.
        answers.append(b"\x1bP1+r" + m.group(1) + b"=\x1b\\")

    if b"\x1b[14t" in buf:
        # Pixelgröße, ~19px/Zeile und ~8px/Spalte bei einer 13px-Monospace-Zelle.
        answers.append(b"\x1b[4;%d;%dt" % (rows * 19, cols * 8))

    for a in answers:
        try:
            tty.write(a)
        except OSError:
            break


def kill_tty(tty: TtyHandle, grace: float = 2.0) -> None:
    """Beenden an das TtyHandle durchreichen (Windows ConPTY, POSIX Prozessgruppe)."""
    tty.kill(grace)
