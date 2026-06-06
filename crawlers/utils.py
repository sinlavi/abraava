import logging
from typing import Optional, Dict, Any
from balethon.objects import Message
from core.config import OFFLINE_MODE
from crawlers.itunes import lookup_itunes

logger = logging.getLogger("ABRAAVA:UTILS")

async def get_track(track_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    if OFFLINE_MODE: return None
    return await lookup_itunes(track_id, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آهنگ از آیتیونز...*")

async def get_or_crawl_artist(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    return await lookup_itunes(artist_id, bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات هنرمند...*")

async def get_or_crawl_collection(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    return await lookup_itunes(collection_id, bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آلبوم...*")

async def get_or_crawl_artist_collections(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    return await lookup_itunes(artist_id, "album", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آلبوم‌های هنرمند از آیتیونز...*")

async def get_or_crawl_collection_tracks(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None
    data = await lookup_itunes(collection_id, "song", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آهنگ‌های آلبوم از آیتیونز...*")
    if data and data.get("results"):
        # Skipping the first entry as it's usually the collection metadata, not a track
        data["results"] = data["results"][1:]
        data["resultCount"] = len(data["results"])
    return data
