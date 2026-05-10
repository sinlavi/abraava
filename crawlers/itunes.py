import json
from typing import Optional, Dict, Any

from config import ITUNES_BASE_URL, HttpClient, OFFLINE_MODE, logger


async def fetch_itunes(endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
    if OFFLINE_MODE:
        logger.info(f"Offline mode: skipping iTunes API call to {endpoint}")
        return None
    session = await HttpClient.get_session()
    url = f"{ITUNES_BASE_URL}/{endpoint}"
    try:
        async with session.get(url, params=params, ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON from {url}")
                    return None
            else:
                logger.warning(f"iTunes API returned status {resp.status} for {url}")
                # If rate limited (429) or other error, could fallback to local DB
    except Exception as e:
        logger.error(f"Error fetching from iTunes API ({endpoint}): {e}")
    return None


async def search_itunes(term: str, entity: Optional[str] = None, limit: int = 50) -> Optional[Dict[str, Any]]:
    logger.info(f"Searching iTunes: term='{term}', entity='{entity}'")
    params = {"term": term, "media": "music", "limit": limit, "country": "US"}
    if entity:
        params["entity"] = entity
    return await fetch_itunes("search", params)


async def lookup_itunes(id: int, entity: Optional[str] = None) -> Optional[Dict[str, Any]]:
    logger.info(f"Looking up iTunes: id={id}, entity={entity}")
    params = {"id": id, "country": "US"}
    if entity:
        params["entity"] = entity
    return await fetch_itunes("lookup", params)
