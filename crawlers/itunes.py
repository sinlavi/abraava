import asyncio
import json
import hashlib
import time
from typing import Optional, Dict, Any, Literal
from pathlib import Path

from config import ITUNES_BASE_URL, HttpClient, OFFLINE_MODE, logger, PROXY


class iTunesCache:
    """Cache manager for iTunes API responses"""

    def __init__(self, cache_dir: str = "cache/itunes", ttl_seconds: int = 4 * 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self._init_cache_dir()

    def _init_cache_dir(self):
        """Create cache directory if it doesn't exist"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, endpoint: str, params: dict) -> str:
        """Generate a unique cache key from endpoint and parameters"""
        key_data = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get file path for a cache key"""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
        """Retrieve cached response if valid"""
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)

            cache_time = cached_data.get("_cache_timestamp", 0)
            current_time = time.time()

            if current_time - cache_time > self.ttl_seconds:
                cache_path.unlink(missing_ok=True)
                return None

            logger.info(
                f"Cache hit for {endpoint} (age: {int((current_time - cache_time) / 60)} minutes)"
            )
            return cached_data.get("response")

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to read cache for {cache_key}: {e}")
            return None

    def set(self, endpoint: str, params: dict, response: Dict[str, Any]):
        """Store response in cache"""
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self._get_cache_path(cache_key)

        cache_data = {
            "_cache_timestamp": time.time(),
            "endpoint": endpoint,
            "params": params,
            "response": response,
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Cached response for {endpoint} (key: {cache_key[:8]}...)")
        except OSError as e:
            logger.error(f"Failed to write cache for {cache_key}: {e}")

    def clear_expired(self):
        """Clear all expired cache entries"""
        current_time = time.time()
        expired_count = 0

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)

                cache_time = cached_data.get("_cache_timestamp", 0)
                if current_time - cache_time > self.ttl_seconds:
                    cache_file.unlink()
                    expired_count += 1
            except (json.JSONDecodeError, KeyError, OSError):
                cache_file.unlink()
                expired_count += 1

        if expired_count > 0:
            logger.info(f"Cleared {expired_count} expired cache entries")

    def clear_all(self):
        """Clear all cache entries"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        logger.info("Cleared all iTunes cache")


_itunes_cache = iTunesCache()


def _has_results(data: Dict[str, Any]) -> bool:
    """Check if iTunes response contains items"""
    if not data:
        return False
    if data.get("resultCount", 0) <= 0:
        return False
    results = data.get("results")
    return isinstance(results, list) and len(results) > 0


async def fetch_itunes(
        endpoint: str,
        params: dict = None,
        bypass_cache: bool = False,
        method: Literal["GET", "POST", "PUT", "DELETE"] = "GET",
        payload: dict = None
) -> Optional[Dict[str, Any]]:
    """Fetch from iTunes API with caching support for multiple HTTP methods"""

    params = params or {}

    # Only use cache for GET requests
    if method == "GET" and not bypass_cache and not OFFLINE_MODE:
        cached_response = _itunes_cache.get(endpoint, params)
        if cached_response is not None:
            return cached_response

    if OFFLINE_MODE:
        logger.info(f"Offline mode: skipping iTunes API call to {endpoint}")
        return None

    session = await HttpClient.get_session()
    url = f"{ITUNES_BASE_URL}/{endpoint}"

    try:
        # Handle different HTTP methods
        if method == "GET":
            async with session.get(url, params=params, ssl=False, proxy=PROXY) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    try:
                        response_data = json.loads(text)

                        # Only cache responses that contain items
                        if not OFFLINE_MODE and _has_results(response_data):
                            _itunes_cache.set(endpoint, params, response_data)

                        return response_data
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON from {url}")
                        return None
                else:
                    logger.warning(f"iTunes API returned status {resp.status} for {url}")

        elif method == "POST":
            async with session.post(url, params=params, json=payload, ssl=False, proxy=PROXY) as resp:
                if resp.status == 200:
                    response_data = await resp.json()
                    return response_data
                else:
                    logger.warning(f"POST to {url} returned status {resp.status}")
                    return None

        elif method == "PUT":
            async with session.put(url, params=params, json=payload, ssl=False, proxy=PROXY) as resp:
                if resp.status == 200:
                    response_data = await resp.json()
                    return response_data
                else:
                    logger.warning(f"PUT to {url} returned status {resp.status}")
                    return None

        elif method == "DELETE":
            async with session.delete(url, params=params, json=payload, ssl=False, proxy=PROXY) as resp:
                if resp.status == 200:
                    response_data = await resp.json()
                    return response_data
                else:
                    logger.warning(f"DELETE to {url} returned status {resp.status}")
                    return None

    except Exception as e:
        logger.error(f"Error fetching from iTunes API ({endpoint}): {e}")

    return None


async def search_itunes(
        term: str,
        entity: Optional[str] = None,
        limit: int = 50,
        bypass_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Search iTunes with caching"""
    logger.info(f"Searching iTunes: term='{term}', entity='{entity}'")
    params = {"term": term, "media": "music", "limit": limit}
    if entity:
        params["entity"] = entity
    return await fetch_itunes("search", params, bypass_cache=bypass_cache)


async def lookup_itunes(
        id: int,
        entity: Optional[str] = None,
        bypass_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Lookup iTunes item with caching"""
    logger.info(f"Looking up iTunes: id={id}, entity={entity}")
    params = {"id": id}
    if entity:
        params["entity"] = entity

    data = await fetch_itunes("lookup", params, bypass_cache=bypass_cache)

    if data and entity and "results" in data:
        if entity == "song":
            entity = "track"
        elif entity == "album":
            entity = "collection"

        filtered_results = [
            item for item in data["results"] if item.get("wrapperType") == entity
        ]
        data["results"] = filtered_results

    return data


async def clear_itunes_cache(expired_only: bool = False):
    """Clear iTunes cache (all or only expired entries)"""
    if expired_only:
        _itunes_cache.clear_expired()
    else:
        _itunes_cache.clear_all()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    cache_files = list(_itunes_cache.cache_dir.glob("*.json"))
    current_time = time.time()

    valid_count = 0
    expired_count = 0

    for cache_file in cache_files:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)

            cache_time = cached_data.get("_cache_timestamp", 0)

            if current_time - cache_time <= _itunes_cache.ttl_seconds:
                valid_count += 1
            else:
                expired_count += 1
        except Exception:
            expired_count += 1

    return {
        "total_files": len(cache_files),
        "valid_entries": valid_count,
        "expired_entries": expired_count,
        "cache_directory": str(_itunes_cache.cache_dir),
        "ttl_hours": _itunes_cache.ttl_seconds / 3600,
    }


async def set_mirror(entity_type: str, entity_id: str, url_type: str, mirror_url: str) -> Optional[Dict[str, Any]]:
    """
    POST /mirror/set
    Sets a mirror URL for a specific entity
    """
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type,
        "mirror_url": mirror_url
    }
    # Use POST method with payload
    return await fetch_itunes("mirror/set", method="POST", payload=payload)


async def get_mirror(entity_type: str, entity_id: str, url_type: str) -> Optional[Dict[str, Any]]:
    """
    GET /mirror/get
    Retrieves a mirror URL for a specific entity
    """
    params = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type
    }
    return await fetch_itunes("mirror/get", params=params, method="GET")


async def delete_mirror(entity_type: str, entity_id: str, url_type: str, method: Literal["POST", "DELETE"] = "POST") -> Optional[Dict[str, Any]]:
    """
    DELETE or POST /mirror/delete
    Deletes a mirror URL for a specific entity
    method: Either "POST" or "DELETE" (default: "POST")
    """
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type
    }

    # Use the unified fetch_itunes function with appropriate method
    return await fetch_itunes("mirror/delete", method=method, payload=payload)