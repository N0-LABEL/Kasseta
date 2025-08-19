import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", "0") or 0) or None
TARGET_VOICE_CHANNEL_ID = int(os.getenv("TARGET_VOICE_CHANNEL_ID", "0") or 0) or None

FOOTBALL_API_PROVIDER = os.getenv("FOOTBALL_API_PROVIDER", "none")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")

LIVE_POLL_SECONDS = int(os.getenv("LIVE_POLL_SECONDS", "60") or 60)

if not DISCORD_TOKEN:
	logger.warning("Переменная окружения DISCORD_TOKEN не задана. Бот не запустится без токена.")