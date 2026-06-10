import os
from dotenv import load_dotenv

load_dotenv()

# Bot Info
BOT_NAME = "ابرآوا"
BOT_USERNAME = "@abraava_bot"
INFO_CHANNEL_USERNAME = "@abraava"
FOOTER = f'\n\n{INFO_CHANNEL_USERNAME}\n{BOT_USERNAME}'
DEEP_LINK_BASE = f"https://ble.ir/{BOT_USERNAME.lstrip('@')}?start="

# Connection Settings
PROXY = os.getenv("proxy", "socks5h://127.0.0.1:1080")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Database and Channel IDs
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
INFO_CHANNEL_ID = os.getenv("INFO_CHANNEL_ID", "5524168471")
ADMIN_IDS = [234591600]

# API Settings
ITUNES_BASE_URL = os.getenv("ITUNES_BASE_URL", "https://3rah.ir/music")
API_BASE_URL = os.getenv("API_BASE_URL", "https://3rah.ir/users/index.php")
API_TOKEN = os.getenv("API_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Spotify Credentials
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Bot Behavior
ITEMS_PER_PAGE = 7
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "False").lower() == "true"
DEFAULT_QUALITY = "192"

# Broadcast and Membership
BROADCAST_CHANNELS = [
    {"username": "@abraava", "name": "ابرآوا", "id": 5524168471},
]
REQUIRED_CHANNELS = [
    {"username": "@abraava", "name": "ابرآوا", "id": 5524168471},
]
BROADCAST_KEYWORDS = ["#اطلاع_رسانی", "#ابرآوا", "#اطلاعیه", "#تبلیغات"]

# Cache Settings
CACHE_DIR = "cache"
SEARCH_CACHE_TTL = 600
SEARCH_CACHE_MAX_ITEMS = 100
MESSAGE_OWNER_TTL = 600
