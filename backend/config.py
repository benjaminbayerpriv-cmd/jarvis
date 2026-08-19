import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")

LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "qwen3.5-9b")

JARVIS_HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.environ.get("JARVIS_PORT", "8000"))

NOTES_FILE = ROOT_DIR / "jarvis_notes.md"
CONFIG_FILE = ROOT_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())
