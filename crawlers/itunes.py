import json, time, asyncio, random, logging, hashlib, os
from typing import Optional, Union, Dict, Any, List, Literal
from core.http_client import HttpClient
from core.config import ITUNES_BASE_URL, OFFLINE_MODE, PROXY_3RAH, PROXY, PLATFORM

logger = logging.getLogger("ABRAAVA:ITUNES")

class iTunesSQLiteCache:
    def __init__(self, db_path="cache/itunes_cache.db", ttl_seconds=86400 * 3):
        self.db_path, self.ttl_seconds, self._db = db_path, ttl_seconds, None
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    async def _get_db(self):
        if self._db is None:
            import aiosqlite
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT, timestamp REAL)"); await self._db.commit()
        return self._db
    def _get_cache_key(self, endpoint: str, params: dict) -> str:
        return hashlib.md5(f"{endpoint}:{json.dumps(params, sort_keys=True)}".encode()).hexdigest()
    async def get(self, endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
        try:
            db = await self._get_db()
            async with db.execute("SELECT response, timestamp FROM cache WHERE key = ?", (self._get_cache_key(endpoint, params),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    if time.time() - row[1] > self.ttl_seconds: await db.execute("DELETE FROM cache WHERE key = ?", (self._get_cache_key(endpoint, params),)); await db.commit(); return None
                    return json.loads(row[0])
        except Exception as e: logger.error(f"Cache read error: {e}"); return None
    async def set(self, endpoint: str, params: dict, response: Dict[str, Any]):
        try:
            db = await self._get_db(); await db.execute("INSERT OR REPLACE INTO cache (key, response, timestamp) VALUES (?, ?, ?)", (self._get_cache_key(endpoint, params), json.dumps(response), time.time())); await db.commit()
        except Exception as e: logger.error(f"Cache write error: {e}")
    async def close(self):
        if self._db: await self._db.close(); self._db = None

_itunes_cache = iTunesSQLiteCache()
ALTERNATIVE_ENDPOINTS = [ITUNES_BASE_URL, "https://itunes.apple.com", "https://ax.itunes.apple.com", "https://buy.itunes.apple.com"]
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"]

class iTunesEndpointManager:
    def __init__(self, endpoints: List[str]): self.endpoints, self.current_index, self.failures = endpoints, 0, {e: 0 for e in endpoints}
    def get_endpoint(self) -> str: return self.endpoints[self.current_index]
    def report_failure(self, endpoint: str):
        self.failures[endpoint] += 1
        if self.failures[endpoint] >= 2: self.current_index = (self.current_index + 1) % len(self.endpoints); logger.warning(f"iTunes endpoint switched to {self.get_endpoint()}")
    def report_success(self, endpoint: str): self.failures[endpoint] = 0

endpoint_manager = iTunesEndpointManager(ALTERNATIVE_ENDPOINTS)

async def fetch_itunes(endpoint: str, params: dict = None, bypass_cache: bool = False, method: Literal["GET", "POST", "PUT", "DELETE"] = "GET", payload: dict = None, official: bool = False, quality: str = None) -> Optional[Dict[str, Any]]:
    params = params or {}
    if quality: params["quality"] = quality
    if method == "GET" and not bypass_cache and not OFFLINE_MODE:
        cached = await _itunes_cache.get(endpoint, params)
        if cached: return cached
    if OFFLINE_MODE: return None
    is_3rah_specific = any(endpoint.startswith(p) for p in ["mirror", "lyrics", "track/save", "song/save", "collection/save", "album/save", "artist/save"])
    for attempt in range(1 if is_3rah_specific else 3):
        base_url = "https://itunes.apple.com" if official and not is_3rah_specific else (endpoint_manager.get_endpoint() if not is_3rah_specific else ITUNES_BASE_URL)
        url, use_proxy = f"{base_url}/{endpoint.lstrip('/')}", (PROXY_3RAH if "3rah.ir" in base_url else True)
        session, headers = await HttpClient.get_session(use_proxy=use_proxy), {"User-Agent": random.choice(USER_AGENTS), "Platform": PLATFORM}
        try:
            proxy_url = PROXY if (use_proxy and PROXY and not PROXY.startswith("socks")) else None
            if method == "GET":
                async with session.get(url, params=params, headers=headers, ssl=False, proxy=proxy_url, timeout=10) as resp:
                    if resp.status == 200:
                        try: data = await resp.json()
                        except: data = json.loads(await resp.text())
                        if not is_3rah_specific: await _itunes_cache.set(endpoint, params, data); endpoint_manager.report_success(base_url)
                        return data
                    if not is_3rah_specific: endpoint_manager.report_failure(base_url)
            else:
                async with getattr(session, method.lower())(url, params=params, json=payload, headers=headers, ssl=False, proxy=proxy_url, timeout=10) as resp:
                    if resp.status == 200: return await resp.json()
        except Exception as e:
            logger.error(f"iTunes fetch failed: {e}")
            if not is_3rah_specific: endpoint_manager.report_failure(base_url)
        if not is_3rah_specific: await asyncio.sleep(0.5)
    return None

async def search_itunes(term: str, entity: Optional[str] = None, limit: int = 50, official: bool = False, quality: str = None) -> Optional[Dict[str, Any]]: return await fetch_itunes("search", {"term": term, "media": "music", "limit": limit, "entity": entity} if entity else {"term": term, "media": "music", "limit": limit}, official=official, quality=quality)
async def lookup_itunes(id: Union[int, str], entity: Optional[str] = None, bypass_cache: bool = False, official: bool = False, quality: str = None) -> Optional[Dict[str, Any]]: return await fetch_itunes("lookup", {"id": id, "entity": entity} if entity else {"id": id}, bypass_cache=bypass_cache, official=official, quality=quality)
async def set_mirror(entity_type: str, entity_id: Union[int, str], url_type: str, mirror_url: str, quality: str = None) -> Optional[Dict[str, Any]]:
    payload = {"entityType": entity_type, "entityId": str(entity_id), "urlType": url_type, "mirrorUrl": mirror_url, "platform": PLATFORM}
    if quality: payload["quality"] = quality
    result = await fetch_itunes("mirror/set", method="POST", payload=payload)
    if result and result.get("success"): await lookup_itunes(entity_id, entity=entity_type, bypass_cache=True, quality=quality)
    return result

def extract_file_id(url: Optional[str]) -> Optional[str]:
    if not url: return None
    if url.startswith("tg://file/"): return url.replace("tg://file/", "")
    if '<token>/' in url: return url.split('<token>/')[-1]
    return url

async def get_mirror(entity_type: str, entity_id: Union[int, str], url_type: str, quality: str = None) -> Optional[Dict[str, Any]]:
    data = await lookup_itunes(entity_id, entity=entity_type, quality=quality)
    return data["results"][0].get("mirrorUrls") if data and data.get("results") else None

async def get_cached_audio(track_id: Union[int, str], quality: str = None) -> Optional[str]:
    mirrors = await get_mirror('track', track_id, 'audioUrl', quality=quality or "192")
    if mirrors and mirrors.get('audioUrl'):
        if str(mirrors['audioUrl'].get('quality', '')) != str(quality or "192"): return None
        return extract_file_id(mirrors['audioUrl'].get('url'))
    return None

async def get_cached_artwork(entity_type: str, entity_id: Union[int, str]) -> Optional[str]:
    mirrors = await get_mirror(entity_type, entity_id, 'artworkUrl')
    return extract_file_id(mirrors['artworkUrl'].get('url')) if mirrors and mirrors.get('artworkUrl') else None

async def get_cached_preview(track_id: Union[int, str]) -> Optional[str]:
    mirrors = await get_mirror('track', track_id, 'previewUrl')
    return extract_file_id(mirrors['previewUrl'].get('url')) if mirrors and mirrors.get('previewUrl') else None

async def get_lyrics(track_id: Union[int, str]) -> Optional[Dict[str, Any]]:
    data = await fetch_itunes("lyrics/get", params={"id": str(track_id)})
    return data["lyrics"] if data and data.get("success") and "lyrics" in data else None

async def set_lyrics(track_id: Union[int, str], lyrics: Dict[str, Any]) -> Optional[Dict[str, Any]]: return await fetch_itunes("lyrics/save", method="POST", payload={"id": str(track_id), "lyrics": lyrics})
async def save_metadata(entity_type: str, data: Union[Dict, List]) -> Optional[Dict[str, Any]]: return await fetch_itunes(f"{entity_type}/save", method="POST", payload=data)
