# config.py
import os

TOKEN = os.getenv("TOKEN")

# Cache TTL settings (seconds)
SEARCH_CACHE_TTL = 3600  # 1 hour
DOWNLOAD_CACHE_TTL = 86400  # 24 hours
