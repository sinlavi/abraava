import hashlib
import pickle
from datetime import time
from pathlib import Path
from typing import Optional, Any, Dict

import asyncio

from config import logger

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

SEARCH_CACHE_TTL = 600
ARTWORK_CACHE_TTL = 86400
PREVIEW_CACHE_TTL = 86400
TRACK_CACHE_TTL = 604800


def get_cache_file_path(cache_key: str) -> Path:
    safe_name = hashlib.md5(cache_key.encode()).hexdigest()
    return CACHE_DIR / f"{safe_name}.cache"


async def save_to_file_cache(cache_key: str, data: Any, ttl: int = SEARCH_CACHE_TTL):
    try:
        cache_path = get_cache_file_path(cache_key)
        cache_data = {
            "data": data,
            "timestamp": time(),
            "ttl": ttl
        }
        # Use pickle for complex objects
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_data, f)
        return True
    except Exception as e:
        logger.error(f"Failed to save to file cache {cache_key}: {e}")
        return False


async def get_from_file_cache(cache_key: str) -> Optional[Any]:
    try:
        cache_path = get_cache_file_path(cache_key)
        if not cache_path.exists():
            return None

        with open(cache_path, 'rb') as f:
            cache_data = pickle.load(f)

        # Check if expired
        if time() - cache_data["timestamp"] > cache_data["ttl"]:
            cache_path.unlink(missing_ok=True)
            return None

        return cache_data["data"]
    except Exception as e:
        logger.error(f"Failed to read from file cache {cache_key}: {e}")
        return None


async def clear_expired_cache():
    """Clear all expired cache files"""
    while True:
        await asyncio.sleep(3600)  # every hour
        try:
            now = time()
            for cache_file in CACHE_DIR.glob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                    if now - cache_data["timestamp"] > cache_data["ttl"]:
                        cache_file.unlink()
                except:
                    cache_file.unlink()  # Remove corrupted files
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")


async def get_search_cache(search_id: str) -> Optional[Dict]:
    """Retrieve search results from memory, check TTL"""
    data = SEARCH_CACHE.get(search_id)
    if data and time() - data["timestamp"] <= SEARCH_CACHE_TTL:
        return data
    if data:
        SEARCH_CACHE.pop(search_id, None)
    return None


async def store_search_cache(search_id: str, type_: str, term: str, results: dict, owner_id: int):
    """Store search results in memory with TTL"""
    if len(SEARCH_CACHE) >= SEARCH_CACHE_MAX_ITEMS:
        oldest = min(SEARCH_CACHE.items(), key=lambda x: x[1]["timestamp"])
        SEARCH_CACHE.pop(oldest[0])
    SEARCH_CACHE[search_id] = {
        "type": type_,
        "term": term,
        "results": results,
        "owner_id": owner_id,
        "timestamp": time()
    }


SEARCH_CACHE = {}
SEARCH_CACHE_MAX_ITEMS = 100
