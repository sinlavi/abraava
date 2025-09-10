import os
import sys
import logging
from cachetools import TTLCache

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')

if not TG_BOT_TOKEN:
    print("TG_BOT_TOKEN environment variable not set", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("abraava")

SEARCH_CACHE = TTLCache(maxsize=1000, ttl=3600)
DOWNLOAD_LINKS_CACHE = TTLCache(maxsize=1000, ttl=3600)

YTDL_EXTRACT_OPTS = {"quiet": True, "extract_flat": True, "skip_download": True}
YTDL_DOWNLOAD_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192"
    }],
}
