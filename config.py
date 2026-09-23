import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _clean(value):
    return (value or "").strip()


TELEGRAM_BOT_TOKEN = _clean(os.environ.get("TELEGRAM_BOT_TOKEN"))
TELEGRAM_CHAT_ID = _clean(os.environ.get("TELEGRAM_CHAT_ID")) or "-1004461281816"
GEMINI_API_KEY = _clean(os.environ.get("GEMINI_API_KEY"))
GEMINI_MODEL = _clean(os.environ.get("GEMINI_MODEL")) or "gemini-3.6-flash"
SERPER_API_KEY = _clean(os.environ.get("SERPER_API_KEY"))

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
NOTES_FILE = DATA_DIR / "notes.json"
DRAFTS_FILE = DATA_DIR / "drafts.json"
VOICE_REFERENCE_DIR = BASE_DIR / "voice_reference"

RECENT_TOPICS_WINDOW_DAYS = 14
MAX_VOICE_EXAMPLES = 4
SEARCH_RESULTS_PER_QUERY = 8


def missing_keys():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not SERPER_API_KEY:
        missing.append("SERPER_API_KEY")
    return missing
