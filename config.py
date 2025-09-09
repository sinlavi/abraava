import os
import sys
import logging
from cachetools import TTLCache

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("BOT_TOKEN environment variable not set", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
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
