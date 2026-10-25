import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# OpenRouter: модели вида "vendor/name" идут туда, а не в Gemini. Ключ необязателен — без него их просто нет.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODELS = [m.strip() for m in os.getenv("OPENROUTER_MODELS", "nvidia/nemotron-3-ultra-550b-a55b:free").split(",")
                     if m.strip()] if OPENROUTER_API_KEY else []
# Прямой канал с Мириком (старший агент, отдельное приложение): общий токен и его адрес
AGENT_LINK_TOKEN = os.getenv("AGENT_LINK_TOKEN", "")
MIRIK_URL = os.getenv("MIRIK_URL", "").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

DB_PATH = os.getenv("DB_PATH", "agent.db")
TZ = os.getenv("TZ_NAME", "Asia/Tashkent")
OWNER_ID = int(os.getenv("OWNER_ID") or 0)
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))
