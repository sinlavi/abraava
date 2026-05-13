import asyncio

from balethon.objects import Message

import db.utils
from config import OFFLINE_MODE, FOOTER, logger
from crawlers.itunes import lookup_itunes
from db.utils import get_artist_collections, insert_collection, get_collection_tracks, insert_track


# ============================================================================
# iTunes Crawling (using relational DB)
# ============================================================================
async def crawl_artist_collections(artist_id: int, status_msg: Message = None):
    """Fetch and store all collections for an artist from iTunes."""
    if OFFLINE_MODE:
        return

    # Check if artist already has collections in DB
    existing = await get_artist_collections(artist_id)

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آلبوم‌های هنرمند...*{FOOTER}")
        except:
            pass

    data = await lookup_itunes(artist_id, "album")
    if data and data.get("resultCount", 0) > 0:
        for item in data["results"]:
            if item.get("wrapperType") == "collection":
                await insert_collection(item)
                # Also crawl collection tracks
                # asyncio.create_task(crawl_collection_tracks(item["collectionId"]))


async def crawl_collection_tracks(collection_id: int, status_msg: Message = None):
    """Fetch and store all tracks for an collection from iTunes."""
    if OFFLINE_MODE:
        return

    collection = await db.utils.get_collection_db(collection_id)
    existing = await get_collection_tracks(collection_id)

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آهنگ‌های آلبوم...*{FOOTER}")
        except:
            pass

    data = await lookup_itunes(collection_id, "song")
    if data and data.get("resultCount", 0) > 0:
        for item in data["results"]:
            if item.get("wrapperType") == "track" and item.get("kind") == "song":
                await insert_track(item)
