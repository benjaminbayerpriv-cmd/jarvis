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
import pty
import re
import signal
import struct
import subprocess
import termios
import fcntl

from . import config

# Overridable via env; the user installed opencode to this binary.
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "/Users/benjaminbayer/.opencode/bin/opencode")

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


def start_tty(workdir: str) -> tuple[int, subprocess.Popen]:
    """Start the real opencode TUI in a PTY; return ``(master_fd, process)``.

    Refreshes the opencode provider config first so the TUI sees the LM Studio
    models, then spawns ``opencode <workdir>`` on an xterm-256color PTY with the
    child in a new session (so it can be signalled as a process group). The
    caller owns the master fd — it reads the raw ANSI stream from it, writes
    keystrokes to it, and resizes it via ``TIOCSWINSZ``.

    Returns the open master fd plus the Popen handle; the caller must hand the
    slot back to the child (close the slave) and reap the process on teardown.
    """
    models = list_models()
    if models:
        ensure_provider_config(models, default_model())

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"

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
    return master, proc


def resize_tty(master: int, proc: subprocess.Popen, cols: int, rows: int) -> None:
    """Tell the PTY its new size and nudge the TUI to reflow (SIGWINCH)."""
    try:
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        return
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGWINCH)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def answer_terminal_queries(master: int, data: bytes, state: dict) -> None:
    """Answer OpenTUI terminal queries xterm.js does not handle.

    opencode's TUI (OpenTUI) probes the terminal and blocks until it gets answers
    to three queries that xterm.js leaves unanswered (it answers DSR, DECRQM,
    DA1 and OSC 10/11 itself, over its ``onData`` hook):

      - ``ESC[>0q``           DA2, secondary device attributes
      - ``ESC P + q <hex> ESC \``  XTGETTCAP, terminfo string query
      - ``ESC[14t``           XTREPORTWIN, window size in pixels

    We keep a short rolling buffer in ``state`` so a query split across two
    ``os.read`` calls is still detected, then write the reply straight into the
    PTY master (the way a real terminal emulator answers).
    """
    # Reset the probe buffer whenever a fresh spawn begins.
    buf = state.get("term_buf", b"") + data
    state["term_buf"] = buf[-512:]
    cols = int(state.get("cols", 80))
    rows = int(state.get("rows", 24))
    answers: list[bytes] = []

    if b"\x1b[>0q" in buf:
        answers.append(b"\x1b[>1;276;0c")  # xterm-like, 256 colour, DA2 reply

    for m in re.finditer(rb"\x1bP\+q([0-9A-Za-z]+)\x1b\\", buf):
        # Declare the requested terminfo string as unsupported (empty value).
        answers.append(b"\x1bP1+r" + m.group(1) + b"=\x1b\\")

    if b"\x1b[14t" in buf:
        # Pixel size, ~19px/row and ~8px/col for a 13px monospace cell.
        answers.append(b"\x1b[4;%d;%dt" % (rows * 19, cols * 8))

    for a in answers:
        try:
            os.write(master, a)
        except OSError:
            break


def kill_tty(proc: subprocess.Popen, grace: float = 2.0) -> None:
    """Terminate the whole opencode process group, escalating to SIGKILL."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    try:
        proc.wait(grace)
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            try:
                proc.wait()
            except Exception:  # noqa: BLE001 - best-effort reap
                pass
