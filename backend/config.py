import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")

LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "google/gemma-4-e4b")

# Optional cloud LLM (DeepSeek, OpenAI-compatible). When DEEPSEEK_API_KEY is
# set, text generation switches to it; screen vision stays on LM Studio, since
# DeepSeek's hosted API has no multimodal model.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# Gemini Vision (Google AI Studio free tier). Used for screen understanding
# when set — DeepSeek's public API has no image input, so this is the cloud
# vision path; LM Studio remains the local fallback when unset.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

JARVIS_HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.environ.get("JARVIS_PORT", "8000"))

NOTES_FILE = ROOT_DIR / "jarvis_notes.md"
CONFIG_FILE = ROOT_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())
