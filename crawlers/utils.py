# ============================================================================
# crawlers/utils.py - بازنویسی توابع کراول با منطق هوشمند
# ============================================================================
import logging
from typing import Optional, Dict, Any

import asyncio
from balethon.objects import Message

from config import OFFLINE_MODE, FOOTER, logger
from crawlers.itunes import lookup_itunes
from db.utils import (
    get_artist_collections,
    get_collection_tracks,
    get_collection_db,
    get_artist_db,
    insert_collection,
    insert_track,
    insert_artist
)


async def should_crawl_artist(artist_id: int, force: bool = False) -> bool:
    if OFFLINE_MODE:
        return False

    if force:
        return True

    artist_data = await get_artist_db(artist_id)
    if not artist_data:
        return True

    collections = await get_artist_collections(artist_id)
    if not collections or collections.get("resultCount", 0) == 0:
        return True

    return False


async def should_crawl_collection(collection_id: int, force: bool = False) -> bool:
    if OFFLINE_MODE:
        return False

    if force:
        return True

    collection_data = await get_collection_db(collection_id)
    if not collection_data:
        return True

    existing_tracks = await get_collection_tracks(collection_id)
    existing_count = existing_tracks.get("resultCount", 0) if existing_tracks else 0
    expected_count = collection_data.get("trackCount", 0)

    if existing_count != expected_count:
        logger.info(f"Collection {collection_id}: track count mismatch ({existing_count} != {expected_count})")
        return True

    return False


async def get_or_crawl_artist_collections(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if not await should_crawl_artist(artist_id, force):
        logger.debug(f"Artist {artist_id} already up-to-date, skipping crawl")
        return

    if OFFLINE_MODE:
        return

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آلبوم‌های هنرمند از iTunes...*{FOOTER}")
        except:
            pass

    await crawl_artist_collections(artist_id)


async def crawl_artist_collections(artist_id):
    data = await lookup_itunes(artist_id, "album")
    if data and data.get("resultCount", 0) > 0:
        for item in data["results"]:
            if item.get("wrapperType") == "collection":
                await insert_collection(item)
                #asyncio.create_task(crawl_collection_tracks(item["collectionId"]))
        logger.info(f"Crawled {data['resultCount']} collections for artist {artist_id}")
    else:
        logger.warning(f"No collections found for artist {artist_id}")


async def get_or_crawl_collection_tracks(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if not await should_crawl_collection(collection_id, force):
        logger.debug(f"Collection {collection_id} already up-to-date, skipping crawl")
        return

    if OFFLINE_MODE:
        return

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آهنگ‌های آلبوم از iTunes...*{FOOTER}")
        except:
            pass

    await crawl_collection_tracks(collection_id)


async def crawl_collection_tracks(collection_id: int):
    data = await lookup_itunes(collection_id, "song")
    if data and data.get("resultCount", 0) > 0:
        for item in data["results"]:
            if item.get("wrapperType") == "track" and item.get("kind") == "song":
                await insert_track(item)

        logger.info(f"Crawled {data['resultCount']} tracks for collection {collection_id}")
    else:
        logger.warning(f"No tracks found for collection {collection_id}")


async def crawl_artist(artist_id, status_msg):
    if OFFLINE_MODE:
        logger.info(f"Offline mode: artist {artist_id} not in local DB")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات هنرمند...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(artist_id)
    if data and data.get("results"):
        for item in data["results"]:
            if item.get("wrapperType") == "artist":
                await insert_artist(item)
        return data


async def crawl_collection(collection_id, status_msg):
    if OFFLINE_MODE:
        logger.info(f"Offline mode: artist {collection_id} not in local DB")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آلبوم...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(collection_id)
    if data and data.get("results"):
        for item in data["results"]:
            if item.get("wrapperType") == "collection":
                await insert_collection(item)
        return data
    return None


async def get_or_crawl_artist(artist_id: int, status_msg: Optional[Message] = None, force: bool = False) -> Optional[
    Dict[str, Any]]:
    db_data = await get_artist_db(artist_id)
    if db_data and not force:
        collections = await get_artist_collections(artist_id)
        if collections and collections.get("resultCount", 0) > 0:
            return db_data

    await crawl_artist(artist_id, status_msg)
    await crawl_artist_collections(artist_id)

    return await get_artist_db(artist_id)


async def get_or_crawl_collection(collection_id: int, status_msg: Optional[Message] = None, force: bool = False) -> \
        Optional[Dict[str, Any]]:
    db_data = await get_collection_db(collection_id)
    if db_data and not force:
        tracks = await get_collection_tracks(collection_id)
        existing_count = tracks.get("resultCount", 0) if tracks else 0
        if existing_count == db_data.get("trackCount", 0) and existing_count > 0:
            return db_data
    await crawl_collection(collection_id, status_msg)
    await crawl_collection_tracks(collection_id)

    return await get_collection_db(collection_id)
