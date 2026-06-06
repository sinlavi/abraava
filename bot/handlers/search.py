from balethon import Client
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from core.logger import logger
from utils.messages import send_message, edit_message
from crawlers.itunes import search_itunes
from bot.handlers.search_results import send_search_results, send_external_search_results
from services.music_adapter import MusicAdapter
import asyncio

music_adapter = MusicAdapter()

async def handle_search(bot: Client, chat_id: int, user_id: int, type_: str, term: str,
                        api_client, search_cache_service, offline_mode=False):
    if type_ in ["ytm", "sc", "sp", "itunes_official"]:
        await handle_external_search(bot, chat_id, user_id, type_, term, search_cache_service)
        return

    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "collection": "آلبوم"}
    logger.info(f"Search: {type_} - {term}")

    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجوی {type_fa_map.get(type_, type_)}: {term}...*", show_cancel=True, user_id=user_id)

    try:
        results = {}
        if not offline_mode:
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack", "collection": "album"}
            entity = entity_map.get(type_)
            itunes_results = await search_itunes(term, entity=entity, limit=50)
            if itunes_results and int(itunes_results.get("resultCount") or 0) > 0:
                results = itunes_results

        if results and int(results.get("resultCount") or 0) > 0:
            await send_search_results(bot, chat_id, type_, term, results, 1, search_cache_service, user_id)
            await status_msg.delete()
            await api_client.log_search(user_id, type_, term, int(results.get("resultCount") or 0))
        else:
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:{type_}:{term}:u{user_id}")]]
            await edit_message(status_msg, f"هیچ نتیجه‌ای برای '{term}' یافت نشد.", reply_markup=retry_markup, user_id=user_id)
    except Exception as e:
        logger.error(f"Search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:{type_}:{term}:u{user_id}")]]
        await edit_message(status_msg, "خطا در جستجو.", reply_markup=retry_markup, user_id=user_id)

async def handle_external_search(bot: Client, chat_id: int, user_id: int, type_: str, term: str, search_cache_service):
    source_map = {"ytm": "یوتیوب موزیک", "sc": "ساندکلاد", "sp": "اسپاتیفای", "itunes_official": "آیتیونز"}
    source_name = source_map.get(type_, "منابع خارجی")
    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجو در {source_name}: {term}...*", show_cancel=True, user_id=user_id)

    try:
        results = []
        if type_ == "ytm":
            results = await music_adapter.search_ytm(term)
        elif type_ == "sc":
            results = await music_adapter.search_sc(term)
        elif type_ == "sp":
            results = await music_adapter.search_spotify(term)
        elif type_ == "itunes_official":
            results = await music_adapter.search_itunes_official(term)

        if results:
            await send_external_search_results(bot, chat_id, type_, term, results, 1, search_cache_service, user_id)
            await status_msg.delete()
        else:
            await edit_message(status_msg, f"هیچ نتیجه‌ای در {source_name} یافت نشد.", user_id=user_id)
    except Exception as e:
        logger.error(f"External search error: {e}")
        await edit_message(status_msg, f"خطا در جستجو در {source_name}.", user_id=user_id)

async def quick_search(bot: Client, chat_id: int, user_id: int, term: str,
                       api_client, user_settings_service, download_service):
    status_msg = await send_message(bot, chat_id, f"⚡ *جستجوی سریع {term}...*", show_cancel=True, user_id=user_id)
    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)
        if results and int(results.get("resultCount") or 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            await download_service.download_and_send_track(chat_id, track_id, user_id, status_msg=status_msg)
            await api_client.log_search(user_id, 'quick', term, 1)
        else:
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}:u{user_id}")]]
            await edit_message(status_msg, "نتیجه‌ای یافت نشد.", reply_markup=retry_markup, user_id=user_id)
    except Exception as e:
        logger.error(f"Quick search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}:u{user_id}")]]
        await edit_message(status_msg, f"خطا در جستجوی سریع: {e}", reply_markup=retry_markup, user_id=user_id)
