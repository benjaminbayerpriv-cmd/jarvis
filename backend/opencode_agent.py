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
import signal
import struct
import subprocess

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

# JARVIS Code: eigene opencode-Binary (Rebrand) mit plattformabhängigem Pfad.
# Per Env überschreibbar: OPENCODE_BIN=/pfad/zum/binary
if os.name == "nt":
    # Windows: lokale JARVIS-Code-Binary (Build-Output unter ~/src/opencode/releases).
    _JARVIS_CODE_BIN = str(pathlib.Path.home() / "src" / "opencode" / "releases" / "jarvis-code-windows-x64.exe")
else:
    _JARVIS_CODE_BIN = "/Users/benjaminbayer/src/opencode/releases/jarvis-code-darwin-arm64"
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", _JARVIS_CODE_BIN)

# Where opencode reads its provider config. We MERGE into it, never overwrite.
OPENCODE_CONFIG = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"

# opencode's system prompt + tools needs roughly this many context tokens.
CODE_MIN_CONTEXT = 24000

# Default working directory for the code agent (overridable via the settings UI).
DEFAULT_CODE_DIR = os.path.expanduser("~/Developer")

# opencode's bundled provider id for our custom OpenAI-compatible provider.
PROVIDER_ID = "lmstudio"


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


def default_model() -> str:
    """Best default for opencode: a loaded model whose context fits opencode.

    Prefers a loaded coder model with enough context, then any loaded model
    with enough context, else falls back to a known-good default. The JARVIS
    chat model is deliberately NOT chosen unconditionally: qwen3.5-9b loads
    with 8192 context and cannot run opencode's ~20k-token system prompt.
    """
    models = list_models()
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


def ensure_provider_config(models: list[dict], default_model_name: str) -> dict:
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
    cfg["model"] = f"{PROVIDER_ID}/{default_model_name}"
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


def start_tty(workdir: str) -> TtyHandle:
    """Starte die echte opencode-TUI in einem PTY/ConPTY; gib einen TtyHandle.

    Aktualisiert zuerst die opencode-Provider-Konfiguration, damit die TUI die
    LM-Studio-Modelle sieht, und startet ``opencode <workdir>`` auf einem
    xterm-256color-Terminal. Auf POSIX läuft der Kindprozess in einer eigenen
    Session (Prozessgruppe → per SIGTERM/SIGWINCH steuerbar); auf Windows
    übernimmt eine pywinpty-PtyProcess (ConPTY). Der Aufrufer besitzt das
    Handle und erklärt sich bereit, es am Ende zu schließen/abzuräumen.
    """
    models = list_models()
    if models:
        ensure_provider_config(models, default_model())

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"

    if WIN:
        if PtyProcess is None:
            raise RuntimeError("pywinpty ist nicht installiert – bitte `pip install pywinpty` ausführen, um den Code-Tab auf Windows zu nutzen.")
        wp = PtyProcess.spawn(
            [OPENCODE_BIN, workdir],
            cwd=workdir or None,
            env=env,
            dimensions=(24, 120),  # rows, cols
        )
        return TtyHandle.windows(wp)

    if pty is None:
        raise RuntimeError("Code-Tab erfordert ein PTY, das auf diesem System nicht verfügbar ist.")

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [OPENCODE_BIN, workdir],
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
