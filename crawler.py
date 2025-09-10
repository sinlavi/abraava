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
    def _prettify_results(results: List[Dict[str, Any]], entity_type="song") -> List[Dict[str, Any]]:
        prettified_results = []
        for result in results:
            if entity_type == "song":
                prettified_results.append({
                    "title": result["trackName"],
                    "url": result["trackViewUrl"],
                    "artist": result["artistName"],
                    "album": result["collectionName"],
                    "coverUrl": result["artworkUrl100"],
                })
        return prettified_results

    class Itunes:
        @staticmethod
        async def search(query: str, limit: int = 5, page: int = 1) -> List[Dict[str, Any]]:
            offset = (page - 1) * limit
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get("https://itunes.apple.com/search", params={
                        "term": query, "media": "music", "limit": limit, "offset": offset
                    })
                    response.raise_for_status()
                    results = response.json().get("results", [])
                    results = Crawler._prettify_results(results)
                    return results
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
    async def get_links(unique_id: str, timeout: float = 10.0) -> Optional[Dict]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                platform = unique_id.split(":")[0].lower()
                unique_id = unique_id.split(":")[1]
                response = await client.get(
                    "https://api.song.link/v1-alpha.1/links?id=" + unique_id + "&type=song&platform=" + platform)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch songlink data for: {e}")
            return {}

    @staticmethod
    async def extract_metadata(links: Optional[Dict]) -> Dict:
        links_by_platform = links.get("linksByPlatform", {})
        itunes = links_by_platform.get("itunes", {}) or {}
        itunes = itunes["entityUniqueId"].split("::")[1]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                metadata = await client.get("https://itunes.apple.com/search", params={
                    "term": itunes, "media": "music", "limit": 1
                })
                metadata.raise_for_status()
                metadata = metadata.json().get("results", [])
                if len(metadata) == 1:
                    metadata = metadata[0]

            print(metadata)
            metadata = {
                "coverUrl": metadata.get("artworkUrl100", "").replace("100x100", "400x400"),
                "title": metadata['trackName'],
                "artist": metadata['artistName'],
                "releaseDate": metadata['releaseDate'],
                "previewUrl": metadata['previewUrl'],
                "album": metadata['collectionName'],
                "genre": metadata['primaryGenreName'],
                "trackNumber": metadata['trackNumber'],
                "trackCount": metadata['trackCount'],
                "discCount": metadata['discCount'],
                "discNumber": metadata['discNumber'],
            }
        except Exception as e:
            logger.error("iTunes search failed: %s", e)
            return {}

        return metadata

    @staticmethod
    def get_download_link(links: Optional[Dict]):
        links_by_platform = links.get("linksByPlatform", {}) or {}
        download_link = links_by_platform.get("soundcloud",
                                              links_by_platform.get("youtube", links_by_platform.get("itunes")))
        return download_link["url"]
