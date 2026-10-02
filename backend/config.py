import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")

# Local, offline, unlimited voice used whenever ElevenLabs isn't available
# (or not configured at all) — see backend/tts.py.
SUPERTONIC_VOICE = os.environ.get("SUPERTONIC_VOICE", "M1")
SUPERTONIC_LANG = os.environ.get("SUPERTONIC_LANG", "de")

# Local speech-to-text (backend/stt.py) — replaces the browser's Web Speech
# API, whose German recognition was complained about repeatedly. Runs on the
# GPU (float16) when CUDA is available, falling back to CPU (int8) only if
# not — "medium" on CPU cost ~2.7s per utterance, which is why "small"
# remains available via WHISPER_MODEL=small for a CPU-only machine.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")
# "auto" (GPU if it works, else CPU), "cpu" or "cuda" — see stt._get_model.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto").strip().lower()

# "127.0.0.1", not "localhost": resolving "localhost" through Python's
# requests/urllib3 on Windows was measured adding ~2s per single request
# (IPv6 "::1" tried first, then a slow fallback to IPv4) — every LM Studio
# call in this app goes through here, so that 2s hit every chat message
# and, doubled up, made the model picker (two sequential calls) take
# 6+ seconds to open. 127.0.0.1 skips the resolution step entirely.
# Trailing slash stripped: a hand-edited ".../v1/" made every f"{base}/models"
# a "//models" and hid the "/v1" suffix from hardware.lm_studio_root(), so the
# native /api/v1/* endpoints were looked up under ".../v1/api/v1/...".
LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").strip().rstrip("/")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "google/gemma-4-e4b")

# API token LM Studio itself requires once its "Require Authentication"
# server setting is on — a prerequisite for "Allow calling servers from
# mcp.json" (see backend/mcp_server.py, which Jarvis's tool-calling depends
# on). Without a token here, every Jarvis request to LM Studio would start
# failing with 401 the moment that setting is enabled. Empty by default —
# only needed once Require Authentication is switched on in LM Studio.
LM_STUDIO_API_TOKEN = os.environ.get("LM_STUDIO_API_TOKEN", "")


def lm_studio_headers() -> dict:
    """Authorization header for a request to LM Studio, or {} when no token
    is configured (LM Studio's Require Authentication is off, the default)."""
    return {"Authorization": f"Bearer {LM_STUDIO_API_TOKEN}"} if LM_STUDIO_API_TOKEN else {}

# Embedding model for semantic memory search (backend/vector_memory.py) —
# served by the same LM Studio instance as the chat model, over its
# OpenAI-compatible /embeddings endpoint. Load it in LM Studio like any
# other model; if it's never loaded, semantic search just falls back to
# memory.py's plain keyword match (see vector_memory.embed).
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")

# Optional cloud LLM (DeepSeek, OpenAI-compatible). When DEEPSEEK_API_KEY is
# set, text generation switches to it; screen vision stays on LM Studio, since
# DeepSeek's hosted API has no multimodal model.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# Which text-generation backend actually answers, when both a DeepSeek key
# and a reachable LM Studio are configured. "auto" (default, unchanged
# legacy behaviour) always prefers DeepSeek when a key exists, only falling
# back to LM Studio on a DeepSeek failure — which made the frontend's model
# picker effectively dead as soon as a DeepSeek key was set: picking an LM
# Studio model there had no effect, DeepSeek kept answering regardless.
# Explicitly "deepseek" or "lmstudio" pins it to one, so a pick in the model
# picker (see llm_client.list_models/select_model in main.py) actually takes
# effect. See llm_client._request_targets for how this is applied.
ACTIVE_PROVIDER = os.environ.get("ACTIVE_PROVIDER", "auto")

# Hard on/off switch for DeepSeek, independent of ACTIVE_PROVIDER above:
# even with ACTIVE_PROVIDER="lmstudio" pinned, DeepSeek still sat in
# llm_client._request_targets() as a fallback for when LM Studio fails —
# meaning it could still get called (and billed) even though the user
# believed they had switched away from it. DEEPSEEK_ENABLED=false removes
# it from the target list entirely (see _request_targets), no fallback, no
# accidental cost, while keeping the key/settings in place so turning it
# back on needs no re-entering anything.
DEEPSEEK_ENABLED = os.environ.get("DEEPSEEK_ENABLED", "true").strip().lower() != "false"

# Gemini (Google AI Studio free tier). Only used by the experimental
# backend/live_voice_test.py speech-to-speech proof-of-concept, not part of
# the normal Jarvis pipeline.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Tavily Search API (free: 1000 Credits/Monat, keine Kreditkarte nötig,
# tavily.com — Brave hat seinen kartenlosen Free-Tier Anfang 2026
# eingestellt). Optional — ohne Key fällt web_search auf das alte Verhalten
# zurück (Suche im verbundenen Browser öffnen statt Ergebnisse zurückzugeben).
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

JARVIS_HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.environ.get("JARVIS_PORT", "8000"))
# Port of the MCP server LM Studio calls Jarvis's tools through (see
# backend/mcp_server.py). Listens on all interfaces, token-protected.
JARVIS_MCP_PORT = int(os.environ.get("JARVIS_MCP_PORT", "8765"))
# Bearer token for that MCP server. Persisted (not regenerated per start):
# LM Studio's SSRF guard blocks the old per-request "ephemeral_mcp" style
# (any non-public server_url, even 127.0.0.1, confirmed live — see
# lmstudio-ai/lms#574), so this server is now registered ONCE in LM
# Studio's own mcp.json instead. A token that changed on every restart
# would make that one-time entry go stale the moment Jarvis restarts.
JARVIS_MCP_TOKEN = os.environ.get("JARVIS_MCP_TOKEN", "")


def ensure_mcp_token() -> str:
    global JARVIS_MCP_TOKEN
    if not JARVIS_MCP_TOKEN:
        import secrets
        JARVIS_MCP_TOKEN = secrets.token_urlsafe(32)
        _persist_env("JARVIS_MCP_TOKEN", JARVIS_MCP_TOKEN)
    return JARVIS_MCP_TOKEN

NOTES_FILE = ROOT_DIR / "jarvis_notes.md"
CONFIG_FILE = ROOT_DIR / "config.json"


# Serializes every read-modify-write of .env and config.json — settings,
# model switch, MCP token and the code agent all write from different
# request threads, and two interleaved writes silently dropped one change.
_write_lock = threading.Lock()


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename, so a crash mid-write can't leave a
    truncated .env/config.json behind (an empty .env loses every key)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_config() -> dict:
    """config.json as a dict — {} when it's missing or not valid JSON (a
    hand-edit with a trailing comma used to 500 the Code tab and the HUD)."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"[config] {CONFIG_FILE.name} nicht lesbar, nutze Standardwerte: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def update_config(**changes) -> dict:
    """Set keys in config.json, keeping every other key, atomically."""
    with _write_lock:
        cfg = load_config()
        cfg.update(changes)
        _atomic_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        return cfg


def _persist_env(key: str, value: str) -> None:
    # A value with a line break would smuggle a second KEY=VALUE line into
    # .env (e.g. a pasted API key with a trailing newline plus more text).
    value = str(value).replace("\r", "").replace("\n", "")
    env_path = ROOT_DIR / ".env"
    with _write_lock:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
        _atomic_write(env_path, "\n".join(lines) + "\n")


def set_lm_studio_base_url(url: str) -> None:
    """Switch the LM Studio endpoint at runtime (chat, embeddings, model
    listing all read config.LM_STUDIO_BASE_URL fresh on every call) and
    persist it to .env so it survives a restart."""
    global LM_STUDIO_BASE_URL
    LM_STUDIO_BASE_URL = url.strip().rstrip("/")
    _persist_env("LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)


# Alle übrigen Einstellungen, die direkt 1:1 auf eine .env-Variable
# abbilden (kein Sonderverhalten wie set_lm_studio_base_url/set_model
# nötig) — die Settings-UI liest/schreibt sie generisch über
# get_simple_settings()/set_simple_setting() statt für jede einen eigenen
# Getter/Setter zu brauchen.
_SIMPLE_SETTINGS = {
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
    "supertonic_voice": "SUPERTONIC_VOICE",
    "supertonic_lang": "SUPERTONIC_LANG",
    "whisper_model": "WHISPER_MODEL",
    "embedding_model": "EMBEDDING_MODEL",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "deepseek_base_url": "DEEPSEEK_BASE_URL",
    "deepseek_model": "DEEPSEEK_MODEL",
    "tavily_api_key": "TAVILY_API_KEY",
    "lm_studio_api_token": "LM_STUDIO_API_TOKEN",
}


def get_simple_settings() -> dict:
    return {name: globals()[env_key] for name, env_key in _SIMPLE_SETTINGS.items()}


def set_simple_setting(name: str, value: str) -> None:
    """Setzt eine der _SIMPLE_SETTINGS zur Laufzeit und persistiert sie in
    .env. Modelle/Clients (tts.py, stt.py, llm_client.py, vector_memory.py),
    die den zugehörigen Wert lesen, tun das jeweils bei jedem Aufruf frisch
    aus diesem Modul — ein Neustart ist dafür nicht nötig, mit der einzigen
    Ausnahme von whisper_model (siehe stt.reset_model(), von main.py nach
    diesem Aufruf separat angestoßen, da stt.py dieses Modul importiert und
    ein Import hier andersrum einen Zirkel wäre)."""
    env_key = _SIMPLE_SETTINGS[name]
    globals()[env_key] = value
    _persist_env(env_key, value)


def set_model(model: str) -> None:
    """Switch the active LM Studio model at runtime and persist it to .env
    so it survives a restart too. llm_client._request_targets() reads
    LM_STUDIO_MODEL fresh on every chat request, so mutating it here takes
    effect on the very next turn — no restart needed for the live switch,
    only for it to have already been the default on process start."""
    global LM_STUDIO_MODEL
    LM_STUDIO_MODEL = model
    _persist_env("LM_STUDIO_MODEL", model)


def set_provider(provider: str) -> None:
    """Pin which text-generation backend _request_targets() tries first —
    see ACTIVE_PROVIDER above. Called from main.py's /models/select whenever
    the frontend's model picker chooses either the synthetic "deepseek:..."
    entry or a real LM Studio one, so a pick there actually takes effect
    instead of a configured DeepSeek key silently overriding it."""
    global ACTIVE_PROVIDER
    if provider not in ("auto", "deepseek", "lmstudio"):
        raise ValueError(f"Unbekannter Provider: {provider!r}")
    ACTIVE_PROVIDER = provider
    _persist_env("ACTIVE_PROVIDER", provider)


def set_deepseek_enabled(enabled: bool) -> None:
    """Toggle DeepSeek on/off, see DEEPSEEK_ENABLED above. Takes effect on
    the very next chat request — llm_client._request_targets() reads it
    fresh every time — no restart needed."""
    global DEEPSEEK_ENABLED
    DEEPSEEK_ENABLED = bool(enabled)
    _persist_env("DEEPSEEK_ENABLED", "true" if enabled else "false")
