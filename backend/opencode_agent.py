"""Headless OpenCode for the JARVIS Code-Tab.

The Code-Tab runs the real OpenCode coding agent, but driven headlessly
(`opencode run --format json`) and rendered as a custom chat UI — no terminal
emulator. This module owns the transport.

Why a PTY: `opencode run --format json` buffers its stdout when it is piped
(block buffering), so nothing reaches the browser until the whole turn is done
and the process exits. Pointing the child's stdout at a *pseudo-terminal*
instead flushes per line, so the events stream to the browser as they are
produced. We never render the terminal — we read raw bytes from the PTY master,
slice them into lines and `json.loads` each one. opencode's own logs go to
stderr (dropped here) so the PTY stream stays pure JSON.

The second constraint surfaced while wiring this up: opencode's system prompt
plus tools is ~20.7k tokens. LM Studio loads a model with a *model-specific*
context length that is NOT its maximum (e.g. google/gemma-4-e4b -> 34304 but
qwen2.5-coder-14b-instruct-uncensored -> 8448). A model whose *loaded* context
is under ~24k cannot run opencode at all (LM Studio returns
`exceed_context_size_error`). The model list the UI sees therefore includes each
model's loaded context so a too-small selection can be flagged instead of
silently failing.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import pty
import subprocess
import threading
from typing import AsyncIterator

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


async def run(
    prompt: str,
    model: str,
    workdir: str,
    session_id: str | None = None,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[dict]:
    """Run one opencode turn, yielding each parsed ``--format json`` event.

    The child's stdout is attached to a PTY so it line-buffers; a reader thread
    pulls bytes off the PTY master and pushes parsed events onto an asyncio
    queue. The process is terminated when ``cancel`` is set or the caller's task
    is cancelled.
    """
    cmd = [OPENCODE_BIN, "run", prompt, "--dir", workdir, "--format", "json"]
    if model:
        cmd += ["-m", f"{PROVIDER_ID}/{model}"]
    if session_id:
        cmd += ["--session", session_id]

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=slave,
        stderr=subprocess.DEVNULL,
        cwd=workdir or None,
        start_new_session=True,
    )
    os.close(slave)  # child owns it now; we only keep the master.

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    buffer = bytearray()

    def _read_and_enqueue() -> None:
        """Blocking reader: pull bytes off the master, split into JSON lines."""
        try:
            while True:
                chunk = os.read(master, 65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    del buffer[: len(line) + 1]
                    ev = _parse_json_line(line)
                    if ev is not None:
                        loop.call_soon_threadsafe(queue.put_nowait, ev)
        except OSError:
            pass
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # EOF sentinel

    thread = threading.Thread(target=_read_and_enqueue, daemon=True)
    thread.start()

    def _shutdown() -> None:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM the whole group
            except (ProcessLookupError, PermissionError):
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

    try:
        while True:
            if cancel is not None and cancel.is_set():
                _shutdown()
                break
            item = await queue.get()
            if item is None:  # EOF / reader done
                break
            yield item
    except asyncio.CancelledError:
        _shutdown()
        raise
    finally:
        _shutdown()
        try:
            await asyncio.to_thread(proc.wait, 2)  # brief grace period
        except Exception:
            if proc.poll() is None:  # noqa: PLR1702
                try:
                    os.killpg(os.getpgid(proc.pid), 9)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                await asyncio.to_thread(proc.wait)
        os.close(master)
        thread.join(timeout=2)


def _parse_json_line(raw: bytes) -> dict | None:
    """Clean one PTY line and parse it as a JSON event; None if it isn't one."""
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None
    # Drop ANSI escapes and stray control chars (e.g. the ^D a wrapper can inject).
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\t")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
