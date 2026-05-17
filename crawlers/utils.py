# ============================================================================
# crawlers/utils.py - بازنویسی توابع کراول با منطق هوشمند
# ============================================================================
import logging
from typing import Optional, Dict, Any

import asyncio
from balethon.objects import Message, InlineKeyboard, InlineKeyboardButton

from config import OFFLINE_MODE, FOOTER, logger
from crawlers.itunes import lookup_itunes


def create_close_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="❌ بستن", callback_data="close")


markup = InlineKeyboard(*[
    [create_close_button()]
])


async def get_artist(artist_id: int, status_msg: Message = None, force: bool = False) -> Optional[Dict[str, Any]]:
    result = await get_or_crawl_artist(artist_id, status_msg, force)
    if result:
        return result
    return None


async def get_collection(collection_id: int, status_msg: Message = None, force: bool = False) -> Optional[
    Dict[str, Any]]:
    result = await get_or_crawl_collection(collection_id, status_msg, force)
    if result:
        return result
    return None


async def get_track(track_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    markup = InlineKeyboard(*[
        [create_close_button()]
    ])
    if OFFLINE_MODE:
        logger.info(f"Offline mode: track {track_id} not in local DB")
        return None

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آهنگ از آیتیونز...*{FOOTER}", reply_markup=markup)
        except Exception:
            pass

    data = await lookup_itunes(track_id)
    return data


async def get_or_crawl_artist_collections(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE:
        return

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آلبوم‌های هنرمند از آیتیونز...*{FOOTER}", reply_markup=markup)
        except:
            pass

    data = await crawl_artist_collections(artist_id)
    return data


async def crawl_artist_collections(artist_id):
    data = await lookup_itunes(artist_id, "album")
    return data


async def get_or_crawl_collection_tracks(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE:
        return

    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آهنگ‌های آلبوم از آیتیونز...*{FOOTER}", reply_markup=markup)
        except:
            pass

    data = await crawl_collection_tracks(collection_id)
    return data


async def crawl_collection_tracks(collection_id: int):
    data = await lookup_itunes(collection_id, "song")
    return data


async def crawl_artist(artist_id, status_msg):
    markup = InlineKeyboard(*[
        [create_close_button()]
    ])
    if OFFLINE_MODE:
        logger.info(f"Offline mode: artist {artist_id} not in local DB")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات هنرمند...*{FOOTER}", reply_markup=markup)
        except:
            pass
    data = await lookup_itunes(artist_id)
    return data


async def crawl_collection(collection_id, status_msg):
    markup = InlineKeyboard(*[
        [create_close_button()]
    ])
    if OFFLINE_MODE:
        logger.info(f"Offline mode: artist {collection_id} not in local DB")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آلبوم...*{FOOTER}", reply_markup=markup)
        except:
            pass
    data = await lookup_itunes(collection_id)
    return data


async def get_or_crawl_artist(artist_id: int, status_msg: Optional[Message] = None, force: bool = False):
    data = await crawl_artist(artist_id, status_msg)
    return data


async def get_or_crawl_collection(collection_id: int, status_msg: Optional[Message] = None, force: bool = False):
    data = await crawl_collection(collection_id, status_msg)
    return data
