import logging
from typing import Optional, Dict, Any
from balethon.objects import Message
from core.config import OFFLINE_MODE
from crawlers.itunes import lookup_itunes

logger = logging.getLogger("ABRAAVA:UTILS")

async def get_track(track_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    if OFFLINE_MODE: return None
    return await lookup_itunes(track_id)

async def get_or_crawl_artist(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    return await lookup_itunes(artist_id)

async def get_or_crawl_collection(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    return await lookup_itunes(collection_id)

async def get_or_crawl_artist_collections(artist_id: int):
    if OFFLINE_MODE: return None
    return await lookup_itunes(artist_id, "album")

async def get_or_crawl_collection_tracks(collection_id: int):
    if OFFLINE_MODE: return None
    return await lookup_itunes(collection_id, "song")
