# caches.py
from cachetools import TTLCache

from config import SEARCH_CACHE_TTL, DOWNLOAD_CACHE_TTL

# Caches with TTL
SEARCH_CACHE = TTLCache(maxsize=500, ttl=SEARCH_CACHE_TTL)
DOWNLOAD_CACHE = TTLCache(maxsize=500, ttl=DOWNLOAD_CACHE_TTL)
