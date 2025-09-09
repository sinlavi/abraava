import httpx
import logging
from typing import Optional, Dict

logger = logging.getLogger("abraava.metadata")

class MetadataFetcher:
    @staticmethod
    async def _fetch_songlink_data(url: str, timeout: float = 10.0) -> Optional[Dict]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get("https://api.song.link/v1-alpha.1/links", params={"url": url})
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch songlink data for {url}: {e}")
            return None

    @staticmethod
    def _extract_itunes_data(songlink_data: Optional[Dict]) -> Dict:
        if not songlink_data:
            return {}
        platforms = songlink_data.get("linksByPlatform", {}) or {}
        itunes = platforms.get("itunes", {}) or {}
        entity_id = itunes.get("entityUniqueId")
        if not entity_id:
            return {}
        return songlink_data.get("entitiesByUniqueId", {}).get(entity_id, {}) or {}

    @staticmethod
    async def get_metadata(url: str, timeout: float = 10.0) -> Dict:
        data = await MetadataFetcher._fetch_songlink_data(url, timeout=timeout)
        return MetadataFetcher._extract_itunes_data(data) if data else {}