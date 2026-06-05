from balethon.objects import CallbackQuery, InlineKeyboard, InlineKeyboardButton
from models.schemas import DownloadQuality
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.search_results import send_search_results
from bot.handlers.album_download import download_album
from bot.handlers.search import handle_search
from bot.handlers.preview import send_voice_preview
import crawlers.utils
from bot.keyboards import get_settings_keyboard, get_quality_keyboard, get_confirmation_keyboard
from utils.messages import send_message, edit_message
from core.config import OFFLINE_MODE
from core.logger import logger
import asyncio

async def handle_callback(bot, callback_query: CallbackQuery, api_client, user_settings_service,
                          artwork_service, search_cache_service, download_service,
                          rate_limiter, download_rate_limiter):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id

    if data == "close":
        try: await callback_query.message.delete()
        except: pass
        return

    if data == "ignore":
        await bot.answer_callback_query(callback_query.id)
        return

    # Settings menus with Confirmation
    if data == "menu_quick_mode":
        current = (await user_settings_service.get_settings(user_id)).quick_mode
        await edit_message(callback_query.message, f"⚡ *تغییر حالت سریع*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("quick_mode", not current))
        return

    if data == "menu_artwork":
        current = (await user_settings_service.get_settings(user_id)).show_artwork
        await edit_message(callback_query.message, f"🖼️ *تغییر نمایش کاور*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("show_artwork", not current))
        return

    if data == "menu_auto_download":
        current = (await user_settings_service.get_settings(user_id)).auto_download
        await edit_message(callback_query.message, f"⚡ *تغییر دانلود خودکار*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("auto_download", not current))
        return

    if data == "menu_notifications":
        current = (await user_settings_service.get_settings(user_id)).notifications
        await edit_message(callback_query.message, f"🔔 *تغییر اعلان‌ها*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("notifications", not current))
        return

    if data.startswith("confirm_"):
        parts = data.split(":")
        setting_type = parts[0].replace("confirm_", "")
        new_value = bool(int(parts[1]))
        update_dict = {setting_type: new_value}
        await user_settings_service.update_settings(user_id, **update_dict)
        await bot.answer_callback_query(callback_query.id, "✅ تنظیمات ذخیره شد")
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "show_quality_menu":
        settings = await user_settings_service.get_settings(user_id)
        await edit_message(callback_query.message, "🎵 *کیفیت دانلود را انتخاب کنید:*",
                          reply_markup=get_quality_keyboard(settings.download_quality))
        return

    if data.startswith("set_quality:"):
        q = data.split(":")[1]
        q_map = {"320": DownloadQuality.HIGH, "192": DownloadQuality.MEDIUM, "128": DownloadQuality.LOW, "ask": DownloadQuality.ASK}
        await user_settings_service.update_settings(user_id, download_quality=q_map[q])
        await bot.answer_callback_query(callback_query.id, f"✅ کیفیت به {q} تغییر یافت")
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "back_to_settings":
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "show_stats":
        from bot.handlers.settings import stats_command_logic
        await stats_command_logic(bot, callback_query.message, user_id, api_client, rate_limiter, download_rate_limiter)
        return

    # Details and Navigation
    parts = data.split(":")
    if data.startswith("artist:"):
        artist_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 1
        is_pag = len(parts) > 2
        await show_artist_page(bot, chat_id, artist_id, page, artwork_service, user_id, callback_query.message, is_pagination=is_pag)
    elif data.startswith("collection:"):
        coll_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 1
        is_pag = len(parts) > 2
        await show_collection_page(bot, chat_id, coll_id, page, artwork_service, user_id, callback_query.message, is_pagination=is_pag)
    elif data.startswith("track:"):
        track_id = int(parts[1])
        await show_track_page(bot, chat_id, track_id, artwork_service, user_id, callback_query.message)
    elif data.startswith("single_album:"):
        coll_id = int(parts[1])
        tracks_data = await crawlers.utils.get_or_crawl_collection_tracks(coll_id)
        if tracks_data and tracks_data.get("results"):
            track_id = tracks_data["results"][0].get("trackId")
            if track_id: await show_track_page(bot, chat_id, track_id, artwork_service, user_id, callback_query.message)
            else: await bot.answer_callback_query(callback_query.id, "❌ خطایی رخ داد", show_alert=True)
    elif data.startswith("recrawl:"):
        type_, eid = parts[1], int(parts[2])
        if type_ == "artist": await show_artist_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True)
        elif type_ == "collection": await show_collection_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True)

    # Searches
    elif data.startswith("page:search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_search_results(bot, chat_id, type_, cached["term"], cached["results"], page,
                                     search_cache_service, user_id, callback_query.message)
        else:
            await bot.answer_callback_query(callback_query.id, "جستجو منقضی شده است", show_alert=True)
    elif data.startswith("refine:"):
        type_ = parts[1]
        term = ":".join(parts[2:])
        await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE)

    # Downloads
    elif data.startswith("download:"):
        track_id = int(parts[1])
        await bot.answer_callback_query(callback_query.id, "⏳ در حال آماده‌سازی...")
        await download_service.download_and_send_track(chat_id, track_id, user_id)
    elif data.startswith("preview:"):
        track_id = int(parts[1])
        await bot.answer_callback_query(callback_query.id, "⏳ در حال دریافت...")
        asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
    elif data.startswith("download_album:"):
        coll_id = int(parts[1])
        await bot.answer_callback_query(callback_query.id, "📀 شروع دانلود آلبوم...")
        asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service))
    elif data.startswith("cancel_album:"):
        owner_id_from_cb, coll_id = int(parts[1]), int(parts[2])
        if user_id == owner_id_from_cb:
            download_service.album_tracker.cancel_download(user_id, coll_id)
            await bot.answer_callback_query(callback_query.id, "⏹️ توقف دانلود...")

    # Retry logic
    elif data.startswith("retry:"):
        retry_data = data[6:]
        if retry_data.startswith("search_retry:"):
            _, t, term = retry_data.split(":", 2)
            await handle_search(bot, chat_id, user_id, t, term, api_client, search_cache_service, OFFLINE_MODE)
        elif retry_data.startswith("download_retry:"):
            _, tid = retry_data.split(":")
            await download_service.download_and_send_track(chat_id, int(tid), user_id)
        try: await callback_query.message.delete()
        except: pass

async def update_settings_msg(bot, message, user_id, user_settings_service):
    settings = await user_settings_service.get_settings(user_id)
    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"
    from core.config import BOT_NAME
    text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت سریع:* {'فعال' if settings.quick_mode else 'غیرفعال'}\n"
        f"🎵 *کیفیت دانلود:* {quality_text}\n"
        f"🖼️ *نمایش کاور:* {'فعال' if settings.show_artwork else 'غیرفعال'}\n"
        f"⚡ *دانلود خودکار:* {'فعال' if settings.auto_download else 'غیرفعال'}\n"
        f"🔔 *دریافت اعلان:* {'فعال' if settings.notifications else 'غیرفعال'}\n"
    )
    markup = get_settings_keyboard(settings.quick_mode, quality_text, settings.show_artwork, settings.auto_download, settings.notifications)
    await edit_message(message, text, reply_markup=markup)
