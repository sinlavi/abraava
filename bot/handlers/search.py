from balethon import Client
from balethon.objects import InlineKeyboardButton
from core.logger import logger
from utils.messages import send_message, edit_message
from crawlers.itunes import search_itunes
from bot.handlers.search_results import send_search_results, send_external_search_results
import yt_dlp
import asyncio
from ytmusicapi import YTMusic

YT = None

async def handle_search(bot: Client, chat_id: int, user_id: int, type_: str, term: str,
                        api_client, search_cache_service, offline_mode=False):
    if type_ in ["ytm", "sc"]:
        await handle_external_search(bot, chat_id, user_id, type_, term, search_cache_service)
        return

    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "collection": "آلبوم"}
    logger.info(f"Search: {type_} - {term}")

    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجوی {type_fa_map.get(type_, type_)}: {term}...*", show_cancel=True)

    try:
        results = {}
        if not offline_mode:
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack", "collection": "album"}
            entity = entity_map.get(type_)
            itunes_results = await search_itunes(term, entity=entity, limit=50)
            if itunes_results and itunes_results.get("resultCount", 0) > 0:
                results = itunes_results

        if results and results.get("resultCount", 0) > 0:
            await send_search_results(bot, chat_id, type_, term, results, 1, search_cache_service, user_id)
            await status_msg.delete()
            await api_client.log_search(user_id, type_, term, results.get("resultCount", 0))
        else:
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:{type_}:{term}")]]
            await edit_message(status_msg, f"هیچ نتیجه‌ای برای '{term}' یافت نشد.", reply_markup=retry_markup)
    except Exception as e:
        logger.error(f"Search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:{type_}:{term}")]]
        await edit_message(status_msg, "خطا در جستجو.", reply_markup=retry_markup)

async def handle_external_search(bot: Client, chat_id: int, user_id: int, type_: str, term: str, search_cache_service):
    source_name = "یوتیوب موزیک" if type_ == "ytm" else "ساندکلاد"
    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجو در {source_name}: {term}...*", show_cancel=True)

    try:
        results = []
        if type_ == "ytm":
            global YT
            if YT is None: YT = YTMusic()
            loop = asyncio.get_event_loop()
            yt_results = await loop.run_in_executor(None, lambda: YT.search(term, filter="songs", limit=20))
            for res in yt_results:
                results.append({
                    "title": res.get("title"),
                    "artist": ", ".join([a.get("name") for a in res.get("artists", [])]),
                    "id": res.get("videoId"),
                    "url": f"https://www.youtube.com/watch?v={res.get('videoId')}",
                    "source": "ytm"
                })
        else: # sc
            ydl_opts = {'quiet': True, 'extract_flat': True, 'force_generic_extractor': False}
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"scsearch20:{term}", download=False))
                if info and 'entries' in info:
                    for entry in info['entries']:
                        results.append({
                            "title": entry.get("title"),
                            "artist": entry.get("uploader", "Unknown"),
                            "id": entry.get("id"),
                            "url": entry.get("url"),
                            "source": "sc"
                        })

        if results:
            await send_external_search_results(bot, chat_id, type_, term, results, 1, search_cache_service, user_id)
            await status_msg.delete()
        else:
            await edit_message(status_msg, f"هیچ نتیجه‌ای در {source_name} یافت نشد.")
    except Exception as e:
        logger.error(f"External search error: {e}")
        await edit_message(status_msg, f"خطا در جستجو در {source_name}.")

async def quick_search(bot: Client, chat_id: int, user_id: int, term: str,
                       api_client, user_settings_service, download_service):
    status_msg = await send_message(bot, chat_id, f"⚡ *جستجوی سریع {term}...*", show_cancel=True)
    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)
        if results and results.get("resultCount", 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            await download_service.download_and_send_track(chat_id, track_id, user_id)
            await api_client.log_search(user_id, 'quick', term, 1)
            await status_msg.delete()
        else:
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}")]]
            await edit_message(status_msg, "نتیجه‌ای یافت نشد.", reply_markup=retry_markup)
    except Exception as e:
        logger.error(f"Quick search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}")]]
        await edit_message(status_msg, f"خطا در جستجوی سریع: {e}", reply_markup=retry_markup)
