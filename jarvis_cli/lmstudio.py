"""Everything the CLI does with LM Studio: reachability, model list, the API
token and the one-time mcp.json entry that gives the model Jarvis' tools.

Talks to LM Studio over plain urllib instead of the backend's requests-based
client, so a connection can be tested and repaired before (or without) the
virtualenv ever being installed.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from . import context as ctx
from .ui import ui

DEFAULT_BASE = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "google/gemma-4-e4b"
DEFAULT_EMBEDDING = "text-embedding-nomic-embed-text-v1.5"

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def base_url() -> str:
    return (ctx.env("LM_STUDIO_BASE_URL") or DEFAULT_BASE).rstrip("/")


def set_base_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    ctx.write_env({"LM_STUDIO_BASE_URL": url})
    return url


def root() -> str:
    """LM Studio's own origin without the OpenAI-compatible /v1 suffix —
    where /api/v1/chat and /api/v1/models live."""
    base = base_url()
    return base[: base.rfind("/v1")].rstrip("/") if base.endswith("/v1") else base


def token() -> str:
    return ctx.env("LM_STUDIO_API_TOKEN")


def set_token(value: str) -> None:
    ctx.write_env({"LM_STUDIO_API_TOKEN": value.strip()})


def headers() -> dict:
    value = token()
    return {"Authorization": f"Bearer {value}"} if value else {}


def model() -> str:
    return ctx.env("LM_STUDIO_MODEL") or DEFAULT_MODEL


def set_model(value: str) -> None:
    ctx.write_env({"LM_STUDIO_MODEL": value.strip()})


def is_local() -> bool:
    return (urlparse(root()).hostname or "").lower() in _LOCAL_HOSTS


def base_url_host() -> str:
    return urlparse(base_url()).hostname or ""


# ------------------------------------------------------------------ probes
def get_json(path: str, timeout: float = 4.0, extra_headers: dict | None = None):
    request_headers = dict(headers())
    request_headers.update(extra_headers or {})
    return ctx.http_json(f"{root()}{path}", timeout=timeout, headers=request_headers)


def health() -> tuple[bool, str]:
    """(reachable, message). Distinguishes 'not running' from 'running but
    wants a token', because the fix for each is completely different."""
    if not base_url():
        return False, "Kein LM-Studio-Endpunkt konfiguriert (LM_STUDIO_BASE_URL)."
    payload, error = get_json("/v1/models")
    if error and "401" in error:
        return False, "LM Studio verlangt ein Token — in LM Studio unter „Manage Tokens“ erzeugen und hier einfügen."
    if error:
        return False, f"LM Studio antwortet nicht auf {base_url()} ({error}). Läuft der Server in LM Studio (Developer → Start Server)?"
    models = [m.get("id") for m in (payload or {}).get("data", []) if m.get("id")]
    if not models:
        return True, "Erreichbar, aber es ist kein Modell geladen."
    if model() not in models:
        return True, f"Erreichbar, {len(models)} Modell(e) geladen — {model()} ist gerade nicht dabei."
    return True, f"Erreichbar, {len(models)} Modell(e) geladen, aktiv: {model()}."


def requires_auth() -> bool:
    """Whether LM Studio answers 401 without a token — the case where the
    address is right and only the credential is missing."""
    _, error = ctx.http_json(f"{root()}/v1/models", timeout=4)
    return error is not None and "401" in error


def loaded_models() -> list[str]:
    """Models currently resident in LM Studio, from the native /api/v1/models
    endpoint (works when LM Studio runs on another machine too)."""
    payload, _ = get_json("/api/v1/models")
    if payload is None:
        return []
    loaded: list[str] = []
    for entry in payload.get("models", []) or []:
        for instance in entry.get("loaded_instances", []) or []:
            if instance.get("id"):
                loaded.append(instance["id"])
    return loaded


def all_models() -> list[dict]:
    """Every model on disk with size and loaded state — LM Studio's /api/v1
    route, falling back to the OpenAI-compatible one (loaded only)."""
    payload, _ = get_json("/api/v1/models")
    if payload is not None:
        models: list[dict] = []
        for entry in payload.get("models", []) or []:
            key, size = entry.get("key") or "", entry.get("size_bytes") or 0
            instances = entry.get("loaded_instances") or []
            if instances:
                # There is no unloaded counterpart bar the map on disk, so one
                # row per residence — the "loaded" UI needs the loaded ids.
                for instance in instances:
                    models.append({"id": instance.get("id") or key, "size": size,
                                   "loaded": True, "type": entry.get("type", "")})
            elif key:
                models.append({"id": key, "size": size, "loaded": False,
                               "type": entry.get("type", "")})
        return models
    payload, _ = get_json("/v1/models")
    return [
        {"id": m.get("id", ""), "size": 0, "loaded": True, "type": ""}
        for m in (payload or {}).get("data", []) if m.get("id")
    ]


def load_model(model_id: str) -> tuple[bool, str]:
    """Ask LM Studio to load a model now (POST /api/v1/models/load) instead of
    waiting for just-in-time loading on the first real message. Works over the
    network, no local `lms` CLI needed."""
    _, error = ctx.http_json(
        f"{root()}/api/v1/models/load", timeout=600,
        headers={**headers(), "Content-Type": "application/json"},
        method="POST", body={"model": model_id},
    )
    if error is None:
        return True, f"{model_id} geladen."
    return False, error


def unload_model(model_id: str) -> tuple[bool, str]:
    _, error = ctx.http_json(
        f"{root()}/api/v1/models/unload", timeout=60,
        headers={**headers(), "Content-Type": "application/json"},
        method="POST", body={"model": model_id},
    )
    return (error is None, error or f"{model_id} entladen.")


def select_model_interactively(auto: bool = True) -> str | None:
    """Pick a chat model: loaded ones first, then everything on disk. Shows
    sizes and marks the embedding models that can't be used for chat."""
    entries = all_models()
    if not entries:
        ui.warn("LM Studio meldet keine Modelle — im LM Studio unter „My Models“ erst eines laden.")
        return None
    unique: dict[str, dict] = {}
    for entry in entries:
        unique.setdefault(entry["id"], entry)
    entries = list(unique.values())
    if auto and len(entries) == 1:
        set_model(entries[0]["id"])
        return entries[0]["id"]

    def label(entry: dict) -> str:
        size = f"{entry['size'] / 1024 ** 3:.1f} GB" if entry["size"] else "?"
        flags = "geladen" if entry["loaded"] else "auf der Festplatte"
        if "embed" in entry["id"].lower():
            flags += " · nur Embeddings, nicht fürs Chatten"
        return f"{entry['id']}   ({size}, {flags})"

    preferred = [i for i, e in enumerate(entries) if "embed" not in e["id"].lower()]
    index = ui.choose("Welches Modell soll Jarvis benutzen?", [(e["id"], label(e)) for e in entries],
                      default=preferred[0] if preferred else 0)
    if index is None:
        return None
    chosen = entries[index]["id"]
    if "embed" in chosen.lower():
        ui.warn("Embedding-Modelle können nicht antworten — bitte ein Chat-Modell wählen.")
        return None
    set_model(chosen)
    return chosen


# ------------------------------------------------------------------- token
def clipboard(text: str | None = None) -> str:
    """Read from or write to the system clipboard, best effort."""
    if ctx.IS_WINDOWS:
        script = (
            f"Set-Clipboard -Value {ps_quote(text)}" if text is not None
            else "Get-Clipboard -Raw"
        )
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=15,
                                 errors="replace", creationflags=ctx.no_window())
            return (out.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    command = ["pbcopy"] if text is not None else ["pbpaste"]
    for candidate in (command, ["xclip", "-selection", "clipboard", "-o"], ["wl-paste"]):
        try:
            out = subprocess.run(candidate, input=text or None, capture_output=True,
                                 text=True, timeout=10, errors="replace")
            if out.returncode == 0:
                return (out.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _looks_like_token(value: str) -> bool:
    return bool(value) and len(value) >= 8 and " " not in value.strip()


def verify_token(value: str) -> tuple[bool, str]:
    payload, error = ctx.http_json(f"{root()}/v1/models", timeout=6,
                                   headers={"Authorization": f"Bearer {value.strip()}"})
    if error and "401" in error:
        return False, "Token wird von LM Studio nicht akzeptiert (401)."
    if error:
        return False, f"LM Studio nicht erreichbar ({error}) — Token kann nicht geprüft werden."
    return True, f"Token gültig, {len((payload or {}).get('data', []))} Modell(e) sichtbar."


def setup_token(interactive: bool = True, from_clipboard: bool = True) -> bool:
    """Paste an LM Studio API token and store it in .env. Accepts it from the
    clipboard (that's how LM Studio's "Manage Tokens" page offers it) or
    typed in masked. Returns True when a verified token is stored."""
    if not interactive:
        value = clipboard() if from_clipboard else ""
        if not _looks_like_token(value):
            ui.fail("Kein Token in der Zwischenablage gefunden.")
            return False
        good, message = verify_token(value)
        (ui.ok if good else ui.fail)(message)
        if good:
            set_token(value)
        return good

    ui.heading("LM-Studio-API-Token")
    ui.note("Nur nötig, wenn in LM Studio „Require Authentication“ eingeschaltet ist — das ist eine "
            "Voraussetzung dafür, dass LM Studio den MCP-Server aus mcp.json aufrufen darf. "
            "Token in LM Studio unter „Manage Tokens“ erzeugen.")
    candidates: list[tuple[str, str]] = []
    pasted = clipboard() if from_clipboard else ""
    if _looks_like_token(pasted):
        candidates.append((pasted, f"Zwischenablage ({ctx.secret(pasted, 6)})"))
    if token():
        candidates.append((token(), f"Gespeichertes Token ({ctx.secret(token(), 6)})"))
    candidates.append(("__type__", "Token manuell eintippen"))
    if not candidates:
        candidates.append(("__type__", "Token manuell eintippen"))

    index = ui.choose("Welches Token soll geprüft werden?", candidates)
    if index is None:
        return False
    value = candidates[index][0]
    if value == "__type__":
        value = ui.ask("LM-Studio-API-Token", password=True)
        if not value:
            return False
    good, message = verify_token(value)
    if not good:
        ui.fail(message)
        if ui.confirm("Trotzdem speichern?", default=False):
            set_token(value)
            ui.warn("Gespeichert — LM Studio wird damit weiterhin 401antworten.")
        return False
    set_token(value)
    ui.ok(message)
    ui.note(f"Token liegt jetzt in {ctx.ENV_FILE.name} (LM_STUDIO_API_TOKEN).")
    return True


def clear_token() -> None:
    set_token("")


# --------------------------------------------------------------------- mcp
def mcp_port() -> int:
    try:
        return int(ctx.env("JARVIS_MCP_PORT") or 8765)
    except ValueError:
        return 8765


def ensure_mcp_token() -> str:
    """The bearer token LM Studio has to send to Jarvis' tool server. Same
    rule as backend/config.ensure_mcp_token: generated once and persisted,
    because the mcp.json entry is written by hand and would go stale on every
    restart otherwise."""
    value = ctx.env("JARVIS_MCP_TOKEN")
    if not value:
        value = secrets.token_urlsafe(32)
        ctx.write_env({"JARVIS_MCP_TOKEN": value})
    return value


def mcp_url() -> str:
    host = "127.0.0.1" if is_local() else ctx.local_ip()
    return f"http://{host}:{mcp_port()}/mcp"


def mcp_snippet() -> dict:
    return {
        "mcpServers": {
            "jarvis": {
                "url": mcp_url(),
                "headers": {"Authorization": f"Bearer {ensure_mcp_token()}"},
            }
        }
    }


def mcp_json_text() -> str:
    return json.dumps(mcp_snippet(), indent=2, ensure_ascii=False)


def mcp_json_paths() -> list[Path]:
    """Where LM Studio may keep its mcp.json — searched rather than assumed,
    since the location differs per version and platform."""
    home = Path.home()
    candidates = [
        home / ".lmstudio" / "mcp.json",
        home / ".config" / "lm-studio" / "mcp.json",
        home / ".lmstudio" / "mcp" / "mcp.json",
    ]
    for variable in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "LM Studio" / "mcp.json")
    return [p for p in candidates if p.exists()]


def install_mcp_entry(target: Path) -> tuple[bool, str]:
    """Merge the jarvis entry into an existing mcp.json, keeping whatever
    other servers are already configured there."""
    try:
        data = json.loads(target.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        return False, f"mcp.json nicht lesbar ({exc})"
    if not isinstance(data, dict):
        return False, "mcp.json hat ein unerwartetes Format."
    servers = data.setdefault("mcpServers", {})
    servers["jarvis"] = mcp_snippet()["mcpServers"]["jarvis"]
    try:
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"mcp.json nicht schreibbar ({exc})"
    return True, f"Jarvis-Eintrag in {target} eingetragen."


def explain_mcp() -> None:
    ui.heading("MCP-Server (Werkzeuge für das Modell)")
    ui.note("Damit Jarvis im Chat wirklich Dateien, Programme und Web öffnen kann, ruft LM Studio "
            "Jarvis' Werkzeuge über einen eigenen MCP-Server auf. Dafür einmalig:")
    ui.out()
    ui.note("  1. In LM Studio: rechte Leiste → „Program“ → „Install“ → „Edit mcp.json“")
    ui.note("  2. Den Block unten einfügen (bei anderen Servern nur den inneren Teil)")
    ui.note("  3. Unter „Developer“ → „Server Settings“ „Allow calling servers from mcp.json“ einschalten")
    ui.note("  4. Falls LM Studio dabei „Require Authentication“ mit einschaltet: Token unter „Manage Tokens“ "
            "erzeugen und in der CLI als LM-Studio-Token hinterlegen")
    ui.out()
    for line in mcp_json_text().splitlines():
        ui.out("    " + ui.paint(line, "grey"))
    ui.out()
    ui.note(f"Adresse: {mcp_url()}" + ("" if is_local() else "  (LM Studio läuft auf einem anderen Rechner)"))
    ui.note("Nach einem Netzwerkwechsel oder einem neuen Token den Block neu ausgeben — "
            "der Eintrag in mcp.json bleibt sonst stehen und passt nicht mehr.")


def native_api_ok() -> bool:
    """Whether the native /api/v1 route answers with the configured token.
    That route is what the mcp.json tool server and LM Studio's own chat use,
    so it's the one that has to work for the rest of Jarvis to function."""
    payload, error = get_json("/api/v1/models")
    return error is None and payload is not None
