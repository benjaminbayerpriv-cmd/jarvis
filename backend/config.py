import json
import os
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

LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "google/gemma-4-e4b")

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

NOTES_FILE = ROOT_DIR / "jarvis_notes.md"
CONFIG_FILE = ROOT_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def set_model(model: str) -> None:
    """Switch the active LM Studio model at runtime and persist it to .env
    so it survives a restart too. llm_client._request_targets() reads
    LM_STUDIO_MODEL fresh on every chat request, so mutating it here takes
    effect on the very next turn — no restart needed for the live switch,
    only for it to have already been the default on process start."""
    global LM_STUDIO_MODEL
    LM_STUDIO_MODEL = model
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("LM_STUDIO_MODEL="):
            lines[i] = f"LM_STUDIO_MODEL={model}"
            break
    else:
        lines.append(f"LM_STUDIO_MODEL={model}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
