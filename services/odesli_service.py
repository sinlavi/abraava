import aiohttp
import re
import asyncio
from typing import Optional, Dict, Any, Tuple
from core.logger import logger
from core.http_client import HttpClient

class OdesliService:
    BASE_URL = "https://api.song.link/v1-alpha.1/links"

    @classmethod
    async def resolve_link(cls, url: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a music link (Spotify, Deezer, etc.) using Odesli.
        Returns a dict with:
        - itunes_id: int (Optional)
        - type: str ('track', 'collection', 'artist')
        - title: str
        - artist: str
        - album: str
        - youtube_url: str (Optional)
        - page_url: str
        """
        session = await HttpClient.get_session()
        params = {"url": url}

        for attempt in range(3):
            try:
                async with session.get(cls.BASE_URL, params=params) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status != 200:
                        return None

                    data = await resp.json()

                    # Extract entities
                    entities = data.get("entitiesByUniqueId", {})

                    # Find any entity to get basic metadata
                    any_entity = next(iter(entities.values())) if entities else {}

                    result = {
                        "itunes_id": None,
                        "type": "track",
                        "title": any_entity.get("title", ""),
                        "artist": any_entity.get("artistName", ""),
                        "album": any_entity.get("albumName", ""),
                        "youtube_url": None,
                        "page_url": data.get("pageUrl")
                    }

                    # Map Odesli types
                    type_map = {"track": "track", "song": "track", "album": "collection", "artist": "artist"}
                    result["type"] = type_map.get(any_entity.get("type"), "track")

                    # Links By Platform
                    links = data.get("linksByPlatform", {})

                    # 1. iTunes/Apple Music
                    itunes_link = links.get("itunes") or links.get("appleMusic")
                    if itunes_link and itunes_link.get("url"):
                        iurl = itunes_link["url"]
                        m = re.search(r'i=(\d+)', iurl) or re.search(r'/(album|song|artist)/([^/]+/)?(\d+)', iurl)
                        if m:
                            result["itunes_id"] = int(m.group(m.lastindex))

                    # 2. YouTube/YouTube Music
                    yt_link = links.get("youtube") or links.get("youtubeMusic")
                    if yt_link:
                        result["youtube_url"] = yt_link.get("url")

                    return result

            except Exception as e:
                logger.error(f"Odesli resolution error: {e}")
                if attempt < 2: await asyncio.sleep(1)

        return None
