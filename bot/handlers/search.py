from balethon import Client
from balethon.objects import Message, InlineKeyboardButton
from core.logger import logger
from utils.messages import send_message
from crawlers.itunes import search_itunes
from bot.handlers.search_results import send_search_results

async def handle_search(bot: Client, chat_id: int, user_id: int, type_: str, term: str,
                        api_client, search_cache_service, offline_mode=False):
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
            await send_message(bot, chat_id, f"هیچ نتیجه‌ای برای '{term}' یافت نشد.", reply_markup=retry_markup)
            await status_msg.delete()
    except Exception as e:
        logger.error(f"Search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:{type_}:{term}")]]
        await send_message(bot, chat_id, "خطا در جستجو.", reply_markup=retry_markup)
        await status_msg.delete()

async def quick_search(bot: Client, chat_id: int, user_id: int, term: str,
                       api_client, user_settings_service, download_service):
    status_msg = await send_message(bot, chat_id, f"⚡ *جستجوی سریع {term}...*", show_cancel=True)
    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)
        if results and results.get("resultCount", 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            settings = await user_settings_service.get_settings(user_id)

            if settings.download_quality.value == "ask":
                # Logic for asking quality could be here, but for now simple download
                await download_service.download_and_send_track(chat_id, track_id, user_id)
            else:
                await download_service.download_and_send_track(chat_id, track_id, user_id)

            await api_client.log_search(user_id, 'quick', term, 1)
            await status_msg.delete()
        else:
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}")]]
            await send_message(bot, chat_id, "نتیجه‌ای یافت نشد.", reply_markup=retry_markup)
            await status_msg.delete()
    except Exception as e:
        logger.error(f"Quick search error: {e}")
        retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:search_retry:track:{term}")]]
        await send_message(bot, chat_id, f"خطا در جستجوی سریع: {e}", reply_markup=retry_markup)
        await status_msg.delete()
