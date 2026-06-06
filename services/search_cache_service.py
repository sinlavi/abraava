import time
from typing import Dict, Any, Optional
from core.config import SEARCH_CACHE_TTL, SEARCH_CACHE_MAX_ITEMS

class SearchCacheService:
    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}

    async def store(self, search_id: str, type_: str, term: str, results: Dict[str, Any], owner_id: int):
        if len(self.cache) >= SEARCH_CACHE_MAX_ITEMS:
            oldest = min(self.cache.items(), key=lambda x: x[1]["timestamp"])
            self.cache.pop(oldest[0])

        self.cache[search_id] = {
            "type": type_,
            "term": term,
            "results": results,
            "owner_id": owner_id,
            "timestamp": time.time()
        }

    async def get(self, search_id: str) -> Optional[Dict[str, Any]]:
        data = self.cache.get(search_id)
        if data and time.time() - data["timestamp"] <= SEARCH_CACHE_TTL:
            return data
        if data:
            self.cache.pop(search_id, None)
        return None

search_cache_service = SearchCacheService()
