import asyncio
import json
import hashlib
import time
import random
import socket
from typing import Optional, Dict, Any, Literal, List, Tuple
from pathlib import Path
from datetime import datetime, timedelta

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

# لیست endpointهای جایگزین برای iTunes API
ALTERNATIVE_ENDPOINTS = [
    "https://itunes.apple.com",  # اصلی
    "https://ax.itunes.apple.com",  # endpoint جایگزین
    "https://buy.itunes.apple.com",  # endpoint جایگزین دیگر
]

# استفاده از متدهای مشابه کد دانلودر
# متدها بر اساس عملکردشان در طول زمان جابجا می‌شوند
ITUNES_METHOD_ORDER = [1, 2, 3]  # روش‌های مختلف برای iTunes API

# User-Agent list (مشابه کد دانلودر)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def _check_proxy() -> Optional[str]:
    """Return SOCKS5 proxy URL if WARP/Dante/etc. is listening on 1080 (مشابه کد دانلودر)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        if s.connect_ex(("127.0.0.1", 1080)) == 0:
            s.close()
            return "socks5://127.0.0.1:1080"
    except Exception:
        pass
    finally:
        s.close()
    return None


def _get_random_headers() -> dict:
    """Generate random browser headers (مشابه کد دانلودر)"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }


class iTunesEndpointManager:
    """مدیریت آندپوینت‌های iTunes با قابلیت تعویض خودکار و استفاده از متدهای مختلف"""
    
    def __init__(self, default_endpoints: List[str]):
        self.default_endpoints = default_endpoints.copy()
        self.active_endpoint = default_endpoints[0]
        self.active_method = 1  # روش فعال (1, 2, 3)
        self.method_order = [1, 2, 3]  # ترتیب روش‌ها
        self.endpoint_stats = {}
        
        for endpoint in default_endpoints:
            self.endpoint_stats[endpoint] = {
                "success_count": 0,
                "fail_count": 0,
                "last_success": None,
                "last_fail": None,
                "consecutive_successes": 0,
                "consecutive_fails": 0,
                "is_blocked": False,
                "blocked_until": None,
                "avg_response_time": 0,
                "total_response_time": 0
            }
        
        self.last_endpoint_switch = time.time()
        self.switch_history = []
        
    def get_proxy_for_method(self, method: int) -> Optional[str]:
        """دریافت پروکسی مناسب برای متد مورد نظر (مشابه کد دانلودر)"""
        proxy = _check_proxy()
        
        # روش‌های 1, 2, 3 با پروکسی
        if method in [1, 2, 3] and proxy:
            return proxy
        # روش‌های دیگه بدون پروکسی
        return None
        
    def get_headers_for_method(self, method: int) -> dict:
        """دریافت هدرهای مناسب برای متد مورد نظر"""
        headers = _get_random_headers()
        
        # برای متدهای مختلف می‌توان هدرهای متفاوت داد
        if method == 2:
            # هدر شبیه موبایل
            headers["User-Agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
        elif method == 3:
            # هدر شبیه تبلت
            headers["User-Agent"] = "Mozilla/5.0 (iPad; CPU OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
            
        return headers
        
    def record_success(self, endpoint: str, method: int, response_time: float):
        """ثبت موفقیت برای یک آندپوینت و روش"""
        if endpoint not in self.endpoint_stats:
            return
            
        stats = self.endpoint_stats[endpoint]
        stats["success_count"] += 1
        stats["last_success"] = time.time()
        stats["consecutive_successes"] += 1
        stats["consecutive_fails"] = 0
        stats["total_response_time"] += response_time
        stats["avg_response_time"] = stats["total_response_time"] / stats["success_count"]
        
        # اگر آندپوینت blocked بوده، آزادش کن
        if stats["is_blocked"]:
            stats["is_blocked"] = False
            stats["blocked_until"] = None
            logger.info(f"🔓 Endpoint {endpoint} is no longer blocked")
        
        # به روز رسانی ترتیب روش‌ها (روش موفق به اول لیست می‌ره)
        if method in self.method_order:
            self.method_order.remove(method)
            self.method_order.insert(0, method)
            logger.debug(f"Method {method} moved to front of order")
        
        # بررسی تعویض آندپوینت
        if endpoint != self.active_endpoint:
            if stats["consecutive_successes"] >= 2:
                self.switch_active_endpoint(endpoint, reason="better_performance")
                
    def record_failure(self, endpoint: str, method: int, error_type: str = "unknown"):
        """ثبت شکست برای یک آندپوینت و روش"""
        if endpoint not in self.endpoint_stats:
            return
            
        stats = self.endpoint_stats[endpoint]
        stats["fail_count"] += 1
        stats["last_fail"] = time.time()
        stats["consecutive_fails"] += 1
        stats["consecutive_successes"] = 0
        
        # به روز رسانی ترتیب روش‌ها (روش ناموفق به آخر لیست می‌ره)
        if method in self.method_order:
            self.method_order.remove(method)
            self.method_order.append(method)
            logger.debug(f"Method {method} moved to end of order")
        
        # اگر ۲ بار پشت سر هم شکست خورد، آندپوینت رو مسدود کن
        if stats["consecutive_fails"] >= 2:
            block_duration = min(30, 5 * stats["consecutive_fails"])
            stats["is_blocked"] = True
            stats["blocked_until"] = time.time() + block_duration
            logger.warning(f"🚫 Endpoint {endpoint} blocked for {block_duration}s")
            
            # اگر آندپوینت فعلی مسدود شد، یه آندپوینت دیگه انتخاب کن
            if endpoint == self.active_endpoint:
                self.find_best_endpoint()
                
    def find_best_endpoint(self) -> str:
        """پیدا کردن بهترین آندپوینت موجود"""
        available_endpoints = []
        
        for endpoint, stats in self.endpoint_stats.items():
            # آندپوینت‌های مسدود شده رو رد کن
            if stats["is_blocked"] and stats["blocked_until"] > time.time():
                continue
                
            # امتیازدهی به آندپوینت‌ها
            score = 0
            if stats["success_count"] > 0:
                success_rate = stats["success_count"] / (stats["success_count"] + stats["fail_count"] + 1)
                score += success_rate * 10
                
                if stats["avg_response_time"] > 0:
                    speed_score = max(0, 5 - (stats["avg_response_time"] / 0.5))
                    score += speed_score
                    
                score += min(3, stats["consecutive_successes"])
                
            available_endpoints.append((score, endpoint))
        
        if not available_endpoints:
            logger.warning("All endpoints are blocked, resetting to default")
            self.reset_all_blocks()
            return self.default_endpoints[0]
            
        available_endpoints.sort(reverse=True, key=lambda x: x[0])
        best_endpoint = available_endpoints[0][1]
        
        if best_endpoint != self.active_endpoint:
            self.switch_active_endpoint(best_endpoint, reason="best_available")
            
        return self.active_endpoint
        
    def switch_active_endpoint(self, new_endpoint: str, reason: str = "manual"):
        """تغییر آندپوینت فعال"""
        old_endpoint = self.active_endpoint
        self.active_endpoint = new_endpoint
        self.last_endpoint_switch = time.time()
        
        self.switch_history.append({
            "timestamp": time.time(),
            "from": old_endpoint,
            "to": new_endpoint,
            "reason": reason
        })
        
        if len(self.switch_history) > 50:
            self.switch_history = self.switch_history[-50:]
            
        logger.info(f"🔄 iTunes endpoint switched: {old_endpoint} → {new_endpoint} (reason: {reason})")
        
    def reset_all_blocks(self):
        """رفع مسدودیت همه آندپوینت‌ها"""
        for stats in self.endpoint_stats.values():
            stats["is_blocked"] = False
            stats["blocked_until"] = None
            stats["consecutive_fails"] = 0
        logger.info("🔓 All iTunes endpoints unblocked")
        
    def get_next_method(self) -> int:
        """دریافت روش بعدی برای امتحان"""
        return self.method_order[0] if self.method_order else 1
        
    def should_reset_to_default(self) -> bool:
        """بررسی بازگشت به آندپوینت اصلی"""
        if self.active_endpoint not in self.default_endpoints:
            return True
            
        if time.time() - self.last_endpoint_switch > 900:  # 15 دقیقه
            default_stats = self.endpoint_stats[self.default_endpoints[0]]
            if default_stats["consecutive_fails"] == 0:
                return True
        return False
        
    def reset_to_default_if_needed(self):
        """بازگشت به آندپوینت اصلی در صورت لزوم"""
        if self.should_reset_to_default():
            self.switch_active_endpoint(self.default_endpoints[0], reason="periodic_reset")


# نمونه از EndpointManager
endpoint_manager = iTunesEndpointManager(ALTERNATIVE_ENDPOINTS)

# تنظیمات timeout
REQUEST_TIMEOUT = 3.5


def _has_results(data: Dict[str, Any]) -> bool:
    """Check if iTunes response contains items"""
    if not data:
        return False
    if data.get("resultCount", 0) <= 0:
        return False
    results = data.get("results")
    return isinstance(results, list) and len(results) > 0


def _has_collection_tracks(data: Dict[str, Any]) -> bool:
    """Check if response contains collection tracks (for caching)"""
    if not data:
        return False
    results = data.get("results", [])
    if not isinstance(results, list) or len(results) == 0:
        return False

    track_count = 0
    for item in results:
        if item.get("wrapperType") == "track" and item.get("collectionId"):
            track_count += 1

    return track_count > 0


def _has_artist_collections(data: Dict[str, Any]) -> bool:
    """Check if response contains artist collections (for caching)"""
    if not data:
        return False
    results = data.get("results", [])
    if not isinstance(results, list) or len(results) == 0:
        return False

    collection_count = 0
    for item in results:
        if item.get("wrapperType") == "collection" and item.get("artistId"):
            collection_count += 1

    return collection_count > 0


def _is_mirror_request(endpoint: str) -> bool:
    """Check if the request is related to mirror operations"""
    return endpoint.startswith("mirror/")


def _should_cache_response(endpoint: str, params: dict, data: Dict[str, Any]) -> bool:
    """Determine if response should be cached based on content"""
    if OFFLINE_MODE:
        return False

    if _is_mirror_request(endpoint):
        return False

    if not data or data.get("resultCount", 0) <= 0:
        return False

    if "entity" in params and params["entity"] == "song":
        if _has_collection_tracks(data):
            logger.info(f"Caching collection tracks response for endpoint {endpoint}")
            return True

    if "entity" in params and params["entity"] == "album":
        if _has_artist_collections(data):
            logger.info(f"Caching artist collections response for endpoint {endpoint}")
            return True

    if endpoint == "search" and _has_results(data):
        return True

    if endpoint == "lookup" and _has_results(data):
        return True

    return False


async def fetch_with_smart_endpoint(
        endpoint: str,
        params: dict = None,
        method: Literal["GET", "POST", "PUT", "DELETE"] = "GET",
        payload: dict = None,
        max_attempts: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Fetch using smart endpoint management with methods similar to downloader
    """
    params = params or {}
    
    # تعیین نوع endpoint اصلی
    if endpoint == "search":
        api_path = "/search"
    elif endpoint == "lookup":
        api_path = "/lookup"
    else:
        api_path = f"/{endpoint}"
    
    # بررسی بازگشت به آندپوینت اصلی
    endpoint_manager.reset_to_default_if_needed()
    
    # بهترین آندپوینت موجود
    best_endpoint = endpoint_manager.find_best_endpoint()
    
    session = await HttpClient.get_session()
    
    for attempt in range(max_attempts):
        # دریافت روش مناسب برای این تلاش
        current_method = endpoint_manager.get_next_method()
        current_endpoint = best_endpoint if attempt == 0 else random.choice(ALTERNATIVE_ENDPOINTS)
        
        # بررسی مسدودیت آندپوینت
        if endpoint_manager.endpoint_stats[current_endpoint]["is_blocked"]:
            continue
            
        url = f"{current_endpoint}{api_path}"
        
        # دریافت پروکسی و هدرهای مناسب برای این روش
        proxy = endpoint_manager.get_proxy_for_method(current_method)
        headers = endpoint_manager.get_headers_for_method(current_method)
        
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=3)
        
        try:
            start_time = time.time()
            logger.info(f"Attempt {attempt + 1}: Trying {current_endpoint} with method {current_method}")
            
            if method == "GET":
                async with session.get(
                    url, 
                    params=params, 
                    headers=headers,
                    ssl=False, 
                    proxy=proxy,
                    timeout=timeout
                ) as resp:
                    elapsed = time.time() - start_time
                    
                    if resp.status == 200:
                        logger.info(f"✅ Success from {current_endpoint} (method {current_method}) in {elapsed:.2f}s")
                        endpoint_manager.record_success(current_endpoint, current_method, elapsed)
                        
                        text = await resp.text()
                        try:
                            response_data = json.loads(text)
                            
                            if _should_cache_response(endpoint, params, response_data):
                                _itunes_cache.set(endpoint, params, response_data)
                            
                            return response_data
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON from {url}")
                            endpoint_manager.record_failure(current_endpoint, current_method, "json_error")
                            continue
                            
                    elif resp.status == 429:
                        logger.warning(f"⚠️ Rate limit (429) from {current_endpoint}")
                        endpoint_manager.record_failure(current_endpoint, current_method, "rate_limit")
                        continue
                    else:
                        logger.warning(f"Status {resp.status} from {current_endpoint}")
                        endpoint_manager.record_failure(current_endpoint, current_method, f"http_{resp.status}")
                        continue
                        
            elif method in ["POST", "PUT", "DELETE"]:
                async with getattr(session, method.lower())(
                    url, 
                    params=params, 
                    headers=headers,
                    json=payload, 
                    ssl=False, 
                    proxy=proxy,
                    timeout=timeout
                ) as resp:
                    elapsed = time.time() - start_time
                    
                    if resp.status == 200:
                        logger.info(f"✅ Success from {current_endpoint} (method {current_method}) in {elapsed:.2f}s")
                        endpoint_manager.record_success(current_endpoint, current_method, elapsed)
                        response_data = await resp.json()
                        return response_data
                    elif resp.status == 429:
                        logger.warning(f"⚠️ Rate limit (429) from {current_endpoint}")
                        endpoint_manager.record_failure(current_endpoint, current_method, "rate_limit")
                        continue
                    else:
                        logger.warning(f"Status {resp.status} from {current_endpoint}")
                        endpoint_manager.record_failure(current_endpoint, current_method, f"http_{resp.status}")
                        continue
                        
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"⏱️ Timeout after {elapsed:.2f}s from {current_endpoint}")
            endpoint_manager.record_failure(current_endpoint, current_method, "timeout")
            continue
            
        except Exception as e:
            logger.warning(f"❌ Error from {current_endpoint}: {e}")
            endpoint_manager.record_failure(current_endpoint, current_method, "exception")
            continue
        
        # تاخیر بین تلاش‌ها (مشابه کد دانلودر)
        await asyncio.sleep(random.uniform(1.0, 3.0))
    
    logger.error(f"❌ All {max_attempts} attempts failed for {endpoint}")
    return None


async def fetch_itunes(
        endpoint: str,
        params: dict = None,
        bypass_cache: bool = False,
        method: Literal["GET", "POST", "PUT", "DELETE"] = "GET",
        payload: dict = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch from iTunes API with smart endpoint management
    """
    params = params or {}

    is_mirror = _is_mirror_request(endpoint)
    if is_mirror:
        bypass_cache = True

    # Check cache for GET requests
    if method == "GET" and not bypass_cache and not OFFLINE_MODE and not is_mirror:
        cached_response = _itunes_cache.get(endpoint, params)
        if cached_response is not None:
            return cached_response

    if OFFLINE_MODE:
        logger.info(f"Offline mode: skipping iTunes API call to {endpoint}")
        return None

    # برای mirror endpoints از روش ساده استفاده کن
    if is_mirror:
        return await fetch_simple_mirror(endpoint, params, method, payload)
    
    # برای iTunes search/lookup از روش هوشمند استفاده کن
    return await fetch_with_smart_endpoint(endpoint, params, method, payload)


async def fetch_simple_mirror(
        endpoint: str,
        params: dict,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        payload: dict = None,
) -> Optional[Dict[str, Any]]:
    """
    درخواست ساده برای mirror endpoints
    """
    from config import ITUNES_BASE_URL
    
    session = await HttpClient.get_session()
    url = f"{ITUNES_BASE_URL}/{endpoint}"
    
    try:
        if method == "GET":
            async with session.get(url, params=params, ssl=False, proxy=PROXY) as resp:
                if resp.status == 200:
                    return await resp.json()
        else:
            async with getattr(session, method.lower())(
                url, params=params, json=payload, ssl=False, proxy=PROXY
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.error(f"Mirror request failed: {e}")
    
    return None


async def get_endpoint_stats() -> Dict[str, Any]:
    """دریافت آمار آندپوینت‌های فعلی"""
    return {
        "active_endpoint": endpoint_manager.active_endpoint,
        "active_method": endpoint_manager.get_next_method(),
        "method_order": endpoint_manager.method_order,
        "endpoints": endpoint_manager.endpoint_stats,
        "switch_history": endpoint_manager.switch_history[-5:]
    }


async def search_itunes(
        term: str,
        entity: Optional[str] = None,
        limit: int = 50,
        bypass_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Search iTunes with smart endpoint management"""
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
    """Lookup iTunes item with smart endpoint management"""
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
        data["resultCount"] = len(filtered_results)

    return data


async def lookup_collection_tracks(
        collection_id: int,
        bypass_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Lookup all tracks in a collection/album"""
    logger.info(f"Looking up collection tracks: collection_id={collection_id}")
    params = {
        "id": collection_id,
        "entity": "song"
    }

    data = await fetch_itunes("lookup", params, bypass_cache=bypass_cache)

    if data and "results" in data:
        tracks = [
            item for item in data["results"]
            if item.get("wrapperType") == "track" and item.get("collectionId") == collection_id
        ]
        data["results"] = tracks
        data["resultCount"] = len(tracks)

    return data


async def lookup_artist_collections(
        artist_id: int,
        bypass_cache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Lookup all collections/albums by an artist"""
    logger.info(f"Looking up artist collections: artist_id={artist_id}")
    params = {
        "id": artist_id,
        "entity": "album"
    }

    data = await fetch_itunes("lookup", params, bypass_cache=bypass_cache)

    if data and "results" in data:
        collections = [
            item for item in data["results"]
            if item.get("wrapperType") == "collection" and item.get("artistId") == artist_id
        ]
        data["results"] = collections
        data["resultCount"] = len(collections)

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


# Mirror endpoints (بدون تغییر)
async def set_mirror(entity_type: str, entity_id: str, url_type: str, mirror_url: str) -> Optional[Dict[str, Any]]:
    """POST /mirror/set"""
    payload = {
        "entityType": entity_type,
        "entityId": entity_id,
        "urlType": url_type,
        "mirrorUrl": mirror_url
    }
    return await fetch_itunes("mirror/set", method="POST", payload=payload)


async def get_mirror(entity_type: str, entity_id: str, url_type: str) -> Optional[Dict[str, Any]]:
    """GET /mirror/get"""
    params = {
        "entityType": entity_type,
        "entityId": entity_id,
        "urlType": url_type
    }
    return await fetch_itunes("mirror/get", params=params, method="GET")


async def delete_mirror(entity_type: str, entity_id: str, url_type: str, method: Literal["POST", "DELETE"] = "POST") -> Optional[Dict[str, Any]]:
    """DELETE or POST /mirror/delete"""
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type
    }
    return await fetch_itunes("mirror/delete", method=method, payload=payload)


async def get_cached_collection_tracks(collection_id: int) -> Optional[Dict[str, Any]]:
    params = {"id": collection_id, "entity": "song"}
    return _itunes_cache.get("lookup", params)


async def get_cached_artist_collections(artist_id: int) -> Optional[Dict[str, Any]]:
    params = {"id": artist_id, "entity": "album"}
    return _itunes_cache.get("lookup", params)
