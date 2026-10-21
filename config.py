import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

DB_PATH = os.getenv("DB_PATH", "agent.db")
TZ = os.getenv("TZ_NAME", "Asia/Tashkent")
OWNER_ID = int(os.getenv("OWNER_ID") or 0)
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))
