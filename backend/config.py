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
    return json.loads(CONFIG_FILE.read_text())
