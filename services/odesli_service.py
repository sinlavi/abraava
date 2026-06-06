import aiohttp
import re
import asyncio
from typing import Optional, Dict, Any, Tuple
from core.logger import logger
from core.http_client import HttpClient

ODESLI_METHODS = [1, 2]

class OdesliService:
    BASE_URL = "https://api.song.link/v1-alpha.1/links"

    @classmethod
    async def resolve_link(cls, url: str) -> Optional[Dict[str, Any]]:
        global ODESLI_METHODS
        session = await HttpClient.get_session()

        from core.config import PROXY
        proxy_url = PROXY
        if not proxy_url:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                if s.connect_ex(("127.0.0.1", 1080)) == 0:
                    proxy_url = "socks5://127.0.0.1:1080"
            except: pass
            finally: s.close()

        for method in list(ODESLI_METHODS):
            try:
                params = {"url": url}
                # method 2 uses proxy if available
                current_proxy = proxy_url if method == 2 else None

                async with session.get(cls.BASE_URL, params=params, proxy=current_proxy, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if method in ODESLI_METHODS:
                            ODESLI_METHODS.remove(method)
                            ODESLI_METHODS.insert(0, method)
                        return cls._parse_response(data)
                    elif resp.status == 429:
                        logger.warning(f"Odesli method {method} rate limited (429)")
                    else:
                        logger.warning(f"Odesli method {method} failed with status {resp.status}")
            except Exception as e:
                logger.debug(f"Odesli method {method} error: {e}")
                if method in ODESLI_METHODS:
                    ODESLI_METHODS.remove(method)
                    ODESLI_METHODS.append(method)

        return None

    @classmethod
    def _parse_response(cls, data: Dict[str, Any]) -> Dict[str, Any]:
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
