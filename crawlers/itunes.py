import asyncio
import json
import hashlib
import time
import random
from typing import Optional, Dict, Any, Literal, List
from pathlib import Path

from core.config import ITUNES_BASE_URL, OFFLINE_MODE, PROXY, FOOTER
from core.logger import logger
from core.http_client import HttpClient
from balethon.objects import Message


class iTunesCache:
    def __init__(self, cache_dir: str = "cache/itunes", ttl_seconds: int = 4 * 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, endpoint: str, params: dict) -> str:
        key_data = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self.cache_dir / f"{cache_key}.json"
        if not cache_path.exists(): return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            if time.time() - cached_data.get("_cache_timestamp", 0) > self.ttl_seconds:
                cache_path.unlink(missing_ok=True)
                return None
            return cached_data.get("response")
        except Exception: return None

    def set(self, endpoint: str, params: dict, response: Dict[str, Any]):
        cache_key = self._get_cache_key(endpoint, params)
        cache_path = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"_cache_timestamp": time.time(), "response": response}, f, ensure_ascii=False, indent=2)
        except Exception: pass

_itunes_cache = iTunesCache()

ALTERNATIVE_ENDPOINTS = [ITUNES_BASE_URL, "https://itunes.apple.com", "https://ax.itunes.apple.com", "https://buy.itunes.apple.com"]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

class iTunesEndpointManager:
    def __init__(self, endpoints: List[str]):
        self.endpoints = endpoints
        self.current_index = 0
        self.failures = {e: 0 for e in endpoints}

    def get_endpoint(self) -> str:
        return self.endpoints[self.current_index]

    def report_failure(self, endpoint: str):
        self.failures[endpoint] += 1
        if self.failures[endpoint] >= 2:
            self.current_index = (self.current_index + 1) % len(self.endpoints)
            logger.warning(f"iTunes endpoint switched to {self.get_endpoint()}")

    def report_success(self, endpoint: str):
        self.failures[endpoint] = 0

endpoint_manager = iTunesEndpointManager(ALTERNATIVE_ENDPOINTS)

async def fetch_itunes(endpoint: str, params: dict = None, bypass_cache: bool = False,
                       method: Literal["GET", "POST", "PUT", "DELETE"] = "GET", payload: dict = None) -> Optional[Dict[str, Any]]:
    params = params or {}
    if method == "GET" and not bypass_cache and not OFFLINE_MODE:
        cached = _itunes_cache.get(endpoint, params)
        if cached: return cached

    if OFFLINE_MODE: return None

    session = await HttpClient.get_session()

    is_mirror = endpoint.startswith("mirror")
    max_attempts = 1 if is_mirror else 3

    for attempt in range(max_attempts):
        base_url = endpoint_manager.get_endpoint() if not is_mirror else ITUNES_BASE_URL
        api_path = f"/{endpoint}" if not endpoint.startswith("/") else endpoint
        url = f"{base_url}{api_path}"

        headers = {"User-Agent": random.choice(USER_AGENTS)}
        try:
            if method == "GET":
                async with session.get(url, params=params, headers=headers, ssl=False, proxy=PROXY, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not is_mirror:
                            _itunes_cache.set(endpoint, params, data)
                            endpoint_manager.report_success(base_url)
                        return data
                    else:
                        if not is_mirror: endpoint_manager.report_failure(base_url)
            else:
                async with getattr(session, method.lower())(url, params=params, json=payload, headers=headers, ssl=False, proxy=PROXY, timeout=10) as resp:
                    if resp.status == 200: return await resp.json()
        except Exception as e:
            logger.error(f"iTunes fetch failed (attempt {attempt+1}): {e}")
            if not is_mirror: endpoint_manager.report_failure(base_url)

        if not is_mirror: await asyncio.sleep(1)

    return None

async def search_itunes(term: str, entity: Optional[str] = None, limit: int = 50) -> Optional[Dict[str, Any]]:
    return await fetch_itunes("search", {"term": term, "media": "music", "limit": limit, "entity": entity} if entity else {"term": term, "media": "music", "limit": limit})

async def lookup_itunes(id: int, entity: Optional[str] = None, bypass_cache: bool = False, status_msg: Message = None, status_text: str = None) -> Optional[Dict[str, Any]]:
    if status_msg and status_text:
        try: await status_msg.edit(f"{status_text}{FOOTER}")
        except: pass
    return await fetch_itunes("lookup", {"id": id, "entity": entity} if entity else {"id": id}, bypass_cache=bypass_cache)

async def set_mirror(entity_type: str, entity_id: str, url_type: str, mirror_url: str, quality: str = None) -> Optional[Dict[str, Any]]:
    payload = {"entityType": entity_type, "entityId": entity_id, "urlType": url_type, "mirrorUrl": mirror_url}
    if quality: payload["quality"] = quality
    return await fetch_itunes("mirror/set", method="POST", payload=payload)

async def get_mirror(entity_type: str, entity_id: str, url_type: str, quality: str = None) -> Optional[Dict[str, Any]]:
    params = {"entityType": entity_type, "entityId": entity_id, "urlType": url_type}
    if quality: params["quality"] = quality
    return await fetch_itunes("mirror/get", params=params)

async def get_cached_audio(track_id: int, quality: str = None) -> Optional[str]:
    data = await get_mirror('track', str(track_id), 'audioUrl', quality=quality or "192")
    if data and data.get("mirrors", {}).get('audioUrl'):
        url = data["mirrors"]['audioUrl']['url']
        return url.split('<token>/')[1] if '<token>' in url else url
    return None

async def get_cached_artwork(entity_type: str, entity_id: int) -> Optional[str]:
    data = await get_mirror(entity_type, str(entity_id), 'artworkUrl')
    if data and data.get("mirrors", {}).get('artworkUrl'):
        url = data["mirrors"]['artworkUrl']['url']
        return url.split('<token>/')[1] if '<token>' in url else url
    return None

async def get_cached_preview(track_id: int) -> Optional[str]:
    data = await get_mirror('track', str(track_id), 'previewUrl')
    if data and data.get("mirrors", {}).get('previewUrl'):
        url = data["mirrors"]['previewUrl']['url']
        return url.split('<token>/')[1] if '<token>' in url else url
    return None
