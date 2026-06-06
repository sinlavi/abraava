import aiohttp
import re
from typing import Optional, Dict, Any, Tuple
from core.logger import logger
from core.http_client import HttpClient

class OdesliService:
    BASE_URL = "https://api.song.link/v1-alpha.1/links"

    @classmethod
    async def resolve_link(cls, url: str) -> Optional[Tuple[str, int]]:
        """
        Resolves a music link (Spotify, Deezer, etc.) to an iTunes ID and type.
        Returns (type, itunes_id) or None.
        type can be 'artist', 'collection', or 'track'.
        """
        session = await HttpClient.get_session()
        params = {
            "url": url
        }

        try:
            async with session.get(cls.BASE_URL, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Odesli API error: {resp.status} - {body}")
                    return None

                data = await resp.json()

                # Look for iTunes entity in entitiesByUniqueId
                entities = data.get("entitiesByUniqueId", {})
                itunes_entity = None
                for entity in entities.values():
                    if entity.get("apiProvider") == "itunes":
                        itunes_entity = entity
                        break

                if not itunes_entity:
                    logger.warning(f"No iTunes entity found for: {url}")
                    return None

                entity_id = itunes_entity.get("id")
                entity_type = itunes_entity.get("type")

                # Mapping Odesli types to our internal types
                type_map = {
                    "track": "track",
                    "song": "track",
                    "album": "collection",
                    "artist": "artist"
                }

                resolved_type = type_map.get(entity_type)
                if not resolved_type or not entity_id:
                    return None

                # For tracks, sometimes the ID is in format album_id/track_id or something similar?
                # Actually for iTunes it should be just the ID.
                # Let's check the itunes link from linksByPlatform if available
                links_by_platform = data.get("linksByPlatform", {})
                itunes_link_data = links_by_platform.get("itunes") or links_by_platform.get("appleMusic")

                if itunes_link_data:
                    itunes_url = itunes_link_data.get("url")
                    if itunes_url:
                        track_match = re.search(r'i=(\d+)', itunes_url)
                        album_match = re.search(r'album/[^/]+/(\d+)', itunes_url)
                        artist_match = re.search(r'artist/[^/]+/(\d+)', itunes_url)

                        if resolved_type == "track" and track_match:
                            return "track", int(track_match.group(1))
                        elif resolved_type == "collection" and album_match:
                            return "collection", int(album_match.group(1))
                        elif resolved_type == "artist" and artist_match:
                            return "artist", int(artist_match.group(1))

                if str(entity_id).isdigit():
                    return resolved_type, int(entity_id)

                return None

        except Exception as e:
            logger.error(f"Error resolving link with Odesli: {e}")
            return None
