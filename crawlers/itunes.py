import asyncio
import json
import hashlib
import time
import random
from typing import Optional, Dict, Any, Literal, List, Union, Tuple
from pathlib import Path
import aiosqlite

from core.config import ITUNES_BASE_URL, OFFLINE_MODE, PROXY, FOOTER
from core.logger import logger
from core.http_client import HttpClient
from balethon.objects import Message
from utils.messages import edit_message


class iTunesSQLiteCache:
    def __init__(self, db_path: str = "cache/itunes_cache.db", ttl_seconds: int = 4 * 3600):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_db(self) -> aiosqlite.Connection:
        async with self._lock:
            if self._db is None:
                self._db = await aiosqlite.connect(self.db_path)
                await self._db.execute(
                    "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT, timestamp REAL)"
                )
                await self._db.commit()
            return self._db

    def _get_cache_key(self, endpoint: str, params: dict) -> str:
        key_data = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    async def get(self, endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
        cache_key = self._get_cache_key(endpoint, params)
        try:
            db = await self._get_db()
            async with db.execute("SELECT response, timestamp FROM cache WHERE key = ?", (cache_key,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    response_json, timestamp = row
                    if time.time() - timestamp > self.ttl_seconds:
                        await db.execute("DELETE FROM cache WHERE key = ?", (cache_key,))
                        await db.commit()
                        return None
                    return json.loads(response_json)
        except Exception as e:
            logger.error(f"Error reading from SQLite cache: {e}")
        return None

    async def set(self, endpoint: str, params: dict, response: Dict[str, Any]):
        cache_key = self._get_cache_key(endpoint, params)
        try:
            db = await self._get_db()
            await db.execute(
                "INSERT OR REPLACE INTO cache (key, response, timestamp) VALUES (?, ?, ?)",
                (cache_key, json.dumps(response), time.time())
            )
            await db.commit()
        except Exception as e:
            logger.error(f"Error writing to SQLite cache: {e}")

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None


_itunes_cache = iTunesSQLiteCache()

ALTERNATIVE_ENDPOINTS = [ITUNES_BASE_URL, "https://itunes.apple.com", "https://ax.itunes.apple.com",
                         "https://buy.itunes.apple.com"]
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
                       method: Literal["GET", "POST", "PUT", "DELETE"] = "GET", payload: dict = None,
                       official: bool = False) -> Optional[Dict[str, Any]]:
    params = params or {}
    if method == "GET" and not bypass_cache and not OFFLINE_MODE:
        cached = await _itunes_cache.get(endpoint, params)
        if cached: return cached

    if OFFLINE_MODE: return None

    session = await HttpClient.get_session()

    is_mirror = endpoint.startswith("mirror")
    max_attempts = 1 if is_mirror else 3

    for attempt in range(max_attempts):
        if official:
            base_url = "https://itunes.apple.com"
        else:
            base_url = endpoint_manager.get_endpoint() if not is_mirror else ITUNES_BASE_URL
        api_path = f"/{endpoint}" if not endpoint.startswith("/") else endpoint
        url = f"{base_url}{api_path}"

        headers = {"User-Agent": random.choice(USER_AGENTS)}
        logger.info(f"iTunes Request [{method}]: {url} - Params: {params}")
        try:
            if method == "GET":
                async with session.get(url, params=params, headers=headers, ssl=False, proxy=PROXY, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not is_mirror:
                            await _itunes_cache.set(endpoint, params, data)
                            endpoint_manager.report_success(base_url)
                        return data
                    else:
                        if not is_mirror: endpoint_manager.report_failure(base_url)
            else:
                async with getattr(session, method.lower())(url, params=params, json=payload, headers=headers,
                                                            ssl=False, proxy=PROXY, timeout=10) as resp:
                    if resp.status == 200: return await resp.json()
        except Exception as e:
            logger.error(f"iTunes fetch failed (attempt {attempt + 1}): {e}")
            if not is_mirror: endpoint_manager.report_failure(base_url)

        if not is_mirror: await asyncio.sleep(0.5)

    return None


async def search_itunes(term: str, entity: Optional[str] = None, limit: int = 50, official: bool = False) -> Optional[
    Dict[str, Any]]:
    return await fetch_itunes("search",
                              {"term": term, "media": "music", "limit": limit, "entity": entity} if entity else {
                                  "term": term, "media": "music", "limit": limit}, official=official)


async def lookup_itunes(id: Union[int, str], entity: Optional[str] = None, bypass_cache: bool = False,
                        official: bool = False) -> Optional[Dict[str, Any]]:
    return await fetch_itunes("lookup", {"id": id, "entity": entity} if entity else {"id": id},
                              bypass_cache=bypass_cache, official=official)


async def set_mirror(entity_type: str, entity_id: Union[int, str], url_type: str, mirror_url: str,
                     quality: str = None) -> Optional[Dict[str, Any]]:
    payload = {"entityType": entity_type, "entityId": str(entity_id), "urlType": url_type, "mirrorUrl": mirror_url}
    if quality: payload["quality"] = quality
    logger.info(f"Setting mirror: {entity_type} {entity_id} {url_type} -> {mirror_url} ({quality})")
    return await fetch_itunes("mirror/set", method="POST", payload=payload)


async def get_mirror(entity_type: str, entity_id: Union[int, str], url_type: str, quality: str = None) -> Optional[
    Dict[str, Any]]:
    params = {"entityType": entity_type, "entityId": str(entity_id), "urlType": url_type}
    if quality: params["quality"] = quality
    logger.info(f"Checking mirror for {entity_type} {entity_id} {url_type} ({quality})")
    return await fetch_itunes("mirror/get", params=params)


async def get_cached_audio(track_id: Union[int, str], quality: str = None) -> Optional[str]:
    data = await get_mirror('track', track_id, 'audioUrl', quality=quality or "192")
    if data and data.get("mirrors", {}).get('audioUrl'):
        if str(data["mirrors"]['audioUrl']['quality']) != str(quality or "192"):
            return None
        url = data["mirrors"]['audioUrl']['url']
        logger.info(f"Cached audio found for {track_id}: {url}")
        return url.split('<token>/')[1] if '<token>' in url else url
    logger.info(f"No cached audio for {track_id} with quality {quality or '192'}")
    return None


async def get_cached_artwork(entity_type: str, entity_id: Union[int, str]) -> Optional[str]:
    data = await get_mirror(entity_type, entity_id, 'artworkUrl')
    if data and data.get("mirrors", {}).get('artworkUrl'):
        url = data["mirrors"]['artworkUrl']['url']
        return url.split('<token>/')[1] if '<token>' in url else url
    return None


async def get_cached_preview(track_id: Union[int, str]) -> Optional[str]:
    data = await get_mirror('track', track_id, 'previewUrl')
    if data and data.get("mirrors", {}).get('previewUrl'):
        url = data["mirrors"]['previewUrl']['url']
        return url.split('<token>/')[1] if '<token>' in url else url
    return None


async def get_lyrics(track_id: Union[int, str]) -> Optional[Dict[str, Any]]:
    logger.info(f"Checking lyrics for {track_id}")
    data = await fetch_itunes("lyrics/get", params={"id": str(track_id)})
    if data and data.get("success") and "lyrics" in data:
        return data["lyrics"]
    return None


async def set_lyrics(track_id: Union[int, str], lyrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    logger.info(f"Setting lyrics for {track_id}")
    return await fetch_itunes("lyrics/save", method="POST", payload={"id": str(track_id), "lyrics": lyrics})
