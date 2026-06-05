import asyncio
from balethon.objects import CallbackQuery, InlineKeyboard, InlineKeyboardButton
from models.schemas import DownloadQuality
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.search_results import send_search_results
from bot.handlers.album_download import download_album
from bot.keyboards import get_settings_keyboard, get_quality_keyboard
from utils.messages import send_message, edit_message
from core.logger import logger

async def handle_callback(bot, callback_query: CallbackQuery, api_client, user_settings_service,
                          artwork_service, search_cache_service, download_service,
                          rate_limiter, download_rate_limiter):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id

    if data == "close":
        await callback_query.message.delete()
        return

    if data == "ignore":
        await bot.answer_callback_query(callback_query.id)
        return

    # Settings menus
    if data == "menu_quick_mode":
        settings = await user_settings_service.get_settings(user_id)
        await user_settings_service.update_settings(user_id, quick_mode=not settings.quick_mode)
        await bot.answer_callback_query(callback_query.id, "تنظیمات بروزرسانی شد")
        # Update message
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "menu_artwork":
        settings = await user_settings_service.get_settings(user_id)
        await user_settings_service.update_settings(user_id, show_artwork=not settings.show_artwork)
        await bot.answer_callback_query(callback_query.id, "تنظیمات بروزرسانی شد")
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "show_quality_menu":
        settings = await user_settings_service.get_settings(user_id)
        await edit_message(callback_query.message, "کیفیت مورد نظر را انتخاب کنید:",
                          reply_markup=get_quality_keyboard(settings.download_quality))
        return

    if data.startswith("set_quality:"):
        q = data.split(":")[1]
        q_map = {"320": DownloadQuality.HIGH, "192": DownloadQuality.MEDIUM, "128": DownloadQuality.LOW, "ask": DownloadQuality.ASK}
        await user_settings_service.update_settings(user_id, download_quality=q_map[q])
        await bot.answer_callback_query(callback_query.id, f"کیفیت به {q} تغییر یافت")
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    if data == "back_to_settings":
        await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
        return

    # Details and Navigation
    parts = data.split(":")
    if data.startswith("artist:"):
        artist_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
        await show_artist_page(bot, chat_id, artist_id, page, artwork_service, user_id, callback_query.message)
    elif data.startswith("collection:"):
        coll_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
        await show_collection_page(bot, chat_id, coll_id, page, artwork_service, user_id, callback_query.message)
    elif data.startswith("track:"):
        track_id = int(parts[1])
        await show_track_page(bot, chat_id, track_id, artwork_service, user_id, callback_query.message)

    # Searches
    elif data.startswith("page:search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_search_results(bot, chat_id, type_, cached["term"], cached["results"], page,
                                     search_cache_service, user_id, callback_query.message)
        else:
            await bot.answer_callback_query(callback_query.id, "جستجو منقضی شده است", show_alert=True)

    # Downloads
    elif data.startswith("download:"):
        track_id = int(parts[1])
        await bot.answer_callback_query(callback_query.id, "در حال آماده‌سازی دانلود...")
        await download_service.download_and_send_track(chat_id, track_id, user_id)
    elif data.startswith("download_album:"):
        coll_id = int(parts[1])
        await bot.answer_callback_query(callback_query.id, "شروع دانلود آلبوم...")
        asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service))
    elif data.startswith("cancel_album:"):
        owner_id_from_cb, coll_id = int(parts[1]), int(parts[2])
        if user_id == owner_id_from_cb:
            download_service.album_tracker.cancel_download(user_id, coll_id)
            await bot.answer_callback_query(callback_query.id, "توقف دانلود...")

async def update_settings_msg(bot, message, user_id, user_settings_service):
    # Instead of full command, just re-edit
    settings = await user_settings_service.get_settings(user_id)
    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"
    from core.config import BOT_NAME
    text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت سریع:* {'فعال' if settings.quick_mode else 'غیرفعال'}\n\n"
        f"🎵 *کیفیت دانلود:* {quality_text}\n\n"
        f"🖼️ *نمایش کاور:* {'فعال' if settings.show_artwork else 'غیرفعال'}\n\n"
        f"⚡ *دانلود خودکار:* {'فعال' if settings.auto_download else 'غیرفعال'}\n\n"
        f"🔔 *دریافت اعلان:* {'فعال' if settings.notifications else 'غیرفعال'}\n"
    )
    markup = get_settings_keyboard(settings.quick_mode, quality_text, settings.show_artwork, settings.auto_download, settings.notifications)
    await edit_message(message, text, reply_markup=markup)
