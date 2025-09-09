import asyncio
import urllib
from urllib.parse import quote

import httpx
import logging
from typing import List, Dict, Any, Optional
from yt_dlp import YoutubeDL
from config import YTDL_EXTRACT_OPTS

logger = logging.getLogger("abraava.Crawler")


class Crawler:
    @staticmethod
    def _search_soundcloud_sync(query: str, limit: int) -> List[Dict[str, Any]]:
        try:
            with YoutubeDL(YTDL_EXTRACT_OPTS) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                return res.get("entries", []) if res else []
        except Exception as e:
            logger.exception("SoundCloud search failed: %s", e)
            return []

    @staticmethod
    async def search_soundcloud(query: str, limit: int = 5) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, Crawler._search_soundcloud_sync, query, limit)

    @staticmethod
    async def search_itunes(query: str, limit: int = 5, page: int = 1) -> List[Dict[str, Any]]:
        offset = (page - 1) * limit
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get("https://itunes.apple.com/search", params={
                    "term": query, "media": "music", "limit": limit, "offset": offset
                })
                response.raise_for_status()
                return response.json().get("results", [])
        except Exception as e:
            logger.error("iTunes search failed: %s", e)
            return []

    @staticmethod
    async def search(query: str, limit: int = 5, page: int = 1) -> List[Dict[str, Any]]:
        sc_task = Crawler.search_soundcloud(query, limit)
        it_task = Crawler.search_itunes(query, limit, page)
        sc, it = await asyncio.gather(sc_task, it_task, return_exceptions=True)
        return ([] if isinstance(sc, Exception) else sc) + ([] if isinstance(it, Exception) else it)

    @staticmethod
    async def get_links(url: str, timeout: float = 10.0) -> Optional[Dict]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get("https://api.song.link/v1-alpha.1/links?url=" + quote(url, safe=''))
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch songlink data for {url}: {e}")
            return None

    @staticmethod
    async def extract_metadata(songlink_data: Optional[Dict]) -> Dict:
        if not songlink_data:
            return {}
        links = songlink_data.get("linksByPlatform", {}) or {}
        itunes = links.get("itunes", {}) or {}
        itunes = itunes["entityUniqueId"].split("::")[1]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                metadata = await client.get("https://itunes.apple.com/search", params={
                    "term": itunes, "media": "music", "limit": 1
                })
                metadata.raise_for_status()
                metadata = metadata.json().get("results", [])
                return metadata
        except Exception as e:
            logger.error("iTunes search failed: %s", e)
            return {}

    @staticmethod
    def get_download_link(songlink_data: Optional[Dict]):
        links = songlink_data.get("linksByPlatform", {}) or {}
        download_link = links.get("soundcloud", links.get("youtube", ""))
        return download_link
