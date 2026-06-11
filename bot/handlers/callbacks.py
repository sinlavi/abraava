from core.bot_client import Button
from models.schemas import DownloadQuality
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.search_results import send_search_results, send_external_search_results
from bot.handlers.album_download import download_album
from bot.handlers.search import handle_search
from bot.handlers.preview import send_voice_preview
from bot.handlers.lyrics import handle_lyrics_request
import crawlers.utils
from bot.keyboards import get_settings_keyboard, get_quality_keyboard, get_confirmation_keyboard, create_close_button
from utils.messages import send_message, edit_message, safe_delete
from core.config import OFFLINE_MODE
from core.logger import logger
import asyncio
import time

DIRECT_LINKS = {} # id -> url

async def store_direct_link(url: str) -> str:
    import uuid
    link_id = uuid.uuid4().hex[:10]
    DIRECT_LINKS[link_id] = url
    return link_id

async def handle_callback(bot, callback_query, api_client, user_settings_service,
                          artwork_service, search_cache_service, download_service,
                          rate_limiter, download_rate_limiter, direct_download_service):
    data = callback_query.data
    parts = data.split(":")
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id

    # Ownership check
    owner_id = None
    new_parts = []
    for part in parts:
        if part.startswith("u") and part[1:].isdigit():
            owner_id = int(part[1:])
        else:
            new_parts.append(part)

    if owner_id and user_id != owner_id:
        await callback_query.answer(text="⚠️ شما دسترسی به این پیام را ندارید. این پیام برای کاربر دیگری ساخته شده است.", show_alert=True)
        return

    # Use cleaned parts for the rest of the logic
    parts = new_parts
    data = ":".join(parts)

    if data == "close":
        await safe_delete(callback_query.message)
        return

    if data.startswith("copy:"):
        # Telethon copy text handling
        # Since we can't truly "copy to clipboard" from server side,
        # we can just answer with the text or instructions.
        # But Telethon doesn't have an easy way to trigger "copy to clipboard" button behavior like Bale.
        # For now, just answer with a tooltip.
        text_to_copy = data[5:]
        await callback_query.answer(text=f"📋 پیوند کپی شد: {text_to_copy}", show_alert=False)
        return

    if data == "help_cmd":
        from bot.handlers.commands import help_command
        await help_command(bot, callback_query.message, is_callback=True)
        return

    if data == "ignore":
        await callback_query.answer(text="")
        return

    # Settings menus with Confirmation
    if data == "menu_quick_mode":
        current = (await user_settings_service.get_settings(user_id)).quick_mode
        message = await edit_message(callback_query.message, f"⚡ *تغییر حالت سریع*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("quick_mode", not current, user_id=user_id))
        return

    if data == "menu_artwork":
        current = (await user_settings_service.get_settings(user_id)).show_artwork
        message = await edit_message(callback_query.message, f"🖼️ *تغییر نمایش کاور*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("show_artwork", not current, user_id=user_id))
        return

    if data == "menu_auto_download":
        current = (await user_settings_service.get_settings(user_id)).auto_download
        message = await edit_message(callback_query.message, f"⚡ *تغییر دانلود خودکار*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("auto_download", not current, user_id=user_id))
        return

    if data == "menu_notifications":
        current = (await user_settings_service.get_settings(user_id)).notifications
        message = await edit_message(callback_query.message, f"🔔 *تغییر اعلان‌ها*\n\nوضعیت فعلی: {'فعال' if current else 'غیرفعال'}\nآیا مایل به تغییر هستید؟",
                          reply_markup=get_confirmation_keyboard("notifications", not current, user_id=user_id))
        return

    if data.startswith("confirm_dl:"):
        link_id = parts[1]
        url = DIRECT_LINKS.get(link_id)
        if url:
            settings = await user_settings_service.get_settings(user_id)
            await callback_query.answer(text="⬇️ در حال دانلود...")
            asyncio.create_task(direct_download_service.download_direct(chat_id, url, user_id, settings.download_quality.value if settings.download_quality.value != "ask" else "192"))
            await safe_delete(callback_query.message)
        else:
            await bot.answer_callback_query(callback_query.id, text="❌ پیوند منقضی شده است", show_alert=True)
        return

    if data.startswith("confirm_") and ":" in data:
        setting_type = parts[0].replace("confirm_", "")
        if setting_type in ["quick_mode", "show_artwork", "auto_download", "notifications"]:
            new_value = bool(int(parts[1]))
            update_dict = {setting_type: new_value}
            await user_settings_service.update_settings(user_id, **update_dict)
            await callback_query.answer(text="✅ تنظیمات ذخیره شد")
            await update_settings_msg(bot, callback_query.message, user_id, user_settings_service)
            return

    if data == "show_quality_menu":
        settings = await user_settings_service.get_settings(user_id)
        message = await edit_message(callback_query.message, "🎵 *کیفیت دانلود را انتخاب کنید:*",
                          reply_markup=get_quality_keyboard(settings.download_quality, user_id=user_id))
        return

    if data.startswith("set_quality:"):
        q = data.split(":")[1]
        q_map = {"320": DownloadQuality.HIGH, "192": DownloadQuality.MEDIUM, "128": DownloadQuality.LOW, "ask": DownloadQuality.ASK}
        await user_settings_service.update_settings(user_id, download_quality=q_map[q])
        await callback_query.answer(text=f"✅ کیفیت به {q} تغییر یافت")
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
    if data.startswith("artist:"):
        artist_id = parts[1]
        if artist_id.isdigit(): artist_id = int(artist_id)
        page = int(parts[2]) if len(parts) > 2 else 1
        is_pag = (len(parts) > 2 and parts[2].isdigit()) # Only True if it's explicitly a page click
        msg_to_edit = callback_query.message if is_pag else None
        await show_artist_page(bot, chat_id, artist_id, page, artwork_service, user_id, msg_to_edit, is_pagination=is_pag)
    elif data.startswith("collection:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        page = int(parts[2]) if len(parts) > 2 else 1
        is_pag = (len(parts) > 2 and parts[2].isdigit()) # Only True if it's explicitly a page click
        msg_to_edit = callback_query.message if is_pag else None
        await show_collection_page(bot, chat_id, coll_id, page, artwork_service, user_id, msg_to_edit, is_pagination=is_pag)
    elif data.startswith("track:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await show_track_page(bot, chat_id, track_id, artwork_service, user_id)
    elif data.startswith("single_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        tracks_data = await crawlers.utils.get_or_crawl_collection_tracks(coll_id)
        if tracks_data and tracks_data.get("results"):
            track_id = tracks_data["results"][0].get("trackId")
            if track_id: await show_track_page(bot, chat_id, track_id, artwork_service, user_id)
            else: await callback_query.answer(text="❌ خطایی رخ داد", show_alert=True)
    elif data.startswith("recrawl:"):
        type_, eid = parts[1], parts[2]
        if eid.isdigit(): eid = int(eid)
        if type_ == "artist": await show_artist_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True)
        elif type_ == "collection": await show_collection_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True)

    elif data.startswith("lyrics:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await handle_lyrics_request(bot, chat_id, track_id, user_id, message_to_edit=None) # Start fresh or edit? Better fresh for long lyrics.
        await callback_query.answer(text="")

    # Searches
    elif data.startswith("page:search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_search_results(bot, chat_id, type_, cached["term"], cached["results"], page,
                                     search_cache_service, user_id, callback_query.message)
        else:
            await callback_query.answer(text="جستجو منقضی شده است", show_alert=True)
    elif data.startswith("refine:"):
        type_ = parts[1]
        term = ":".join(parts[2:])
        await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE)

    elif data.startswith("ext_dl:"):
        link_id = parts[1]
        url = DIRECT_LINKS.get(link_id)
        if url:
            await direct_download_service.ask_confirmation(chat_id, url, user_id=user_id)
        else:
            await callback_query.answer(text="❌ پیوند منقضی شده است", show_alert=True)
        await safe_delete(callback_query.message)

    elif data.startswith("page:ext_search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_external_search_results(bot, chat_id, type_, cached["term"], cached["results"]["results"], page,
                                              search_cache_service, user_id, callback_query.message)
        else:
            await callback_query.answer(text="جستجو منقضی شده است", show_alert=True)

    # Downloads
    elif data.startswith("download:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        settings = await user_settings_service.get_settings(user_id)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [
                [Button(text="🎵 ۳۲۰ kbps", callback_data=f"dl_q:320:{track_id}:u{user_id}")],
                [Button(text="🎶 ۱۹۲ kbps", callback_data=f"dl_q:192:{track_id}:u{user_id}")],
                [Button(text="🎧 ۱۲۸ kbps", callback_data=f"dl_q:128:{track_id}:u{user_id}")],
                [create_close_button(user_id)]
            ]
            await send_message(bot, chat_id, "🎵 *کیفیت دانلود را انتخاب کنید:*", reply_markup=markup)
        else:
            await callback_query.answer(text="⏳ در حال آماده‌سازی...")
            status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود...*", show_cancel=True)
            status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, status_msg=status_msg)

    elif data.startswith("dl_q:"):
        quality, track_id = parts[1], parts[2]
        if track_id.isdigit(): track_id = int(track_id)
        await callback_query.answer(text=f"⏳ دانلود با کیفیت {quality}...")
        # Don't delete, reuse the message as status_msg
        status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, selected_quality=quality, status_msg=callback_query.message)

    elif data.startswith("dl_fb:"):
        quality, track_id = parts[1], parts[2]
        if track_id.isdigit(): track_id = int(track_id)
        await callback_query.answer(text=f"⏳ دانلود با کیفیت {quality}...")
        status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, selected_quality=quality, status_msg=callback_query.message, skip_size_check=True)

    elif data.startswith("preview:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await callback_query.answer(text="⏳ در حال دریافت...")
        asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
    elif data.startswith("download_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        settings = await user_settings_service.get_settings(user_id)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [
                [Button(text="🎵 ۳۲۰ kbps", callback_data=f"dl_aq:320:{coll_id}:u{user_id}")],
                [Button(text="🎶 ۱۹۲ kbps", callback_data=f"dl_aq:192:{coll_id}:u{user_id}")],
                [Button(text="🎧 ۱۲۸ kbps", callback_data=f"dl_aq:128:{coll_id}:u{user_id}")],
                [create_close_button(user_id)]
            ]
            await send_message(bot, chat_id, "📀 *کیفیت دانلود آلبوم را انتخاب کنید:*", reply_markup=markup)
        else:
            await callback_query.answer(text="📀 شروع دانلود آلبوم...")
            status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود آلبوم...*", show_cancel=True)
            asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service, status_msg=status_msg))

    elif data.startswith("dl_aq:"):
        quality, coll_id = parts[1], parts[2]
        if coll_id.isdigit(): coll_id = int(coll_id)
        await callback_query.answer(text=f"📀 شروع دانلود با کیفیت {quality}...")
        # Don't delete, reuse the message as parent status msg in download_album
        asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service, quality=quality, status_msg=callback_query.message))

    elif data.startswith("retry_failed:"):
        failed_ids = parts[1].split(",")
        await callback_query.answer(text="🔄 تلاش مجدد برای قطعات ناموفق...")
        settings = await user_settings_service.get_settings(user_id)
        quality_value = settings.download_quality.value
        if quality_value == "ask": quality_value = "192"
        # Call download_album with retry_ids for systematic batch retry
        asyncio.create_task(download_album(bot, chat_id, None, user_id, download_service, quality=quality_value, status_msg=callback_query.message, retry_ids=failed_ids))

    elif data.startswith("cancel_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        download_service.album_tracker.cancel_download(user_id, coll_id)
        await callback_query.answer(text="⏹️ توقف دانلود...")

    elif data.startswith("force_artwork:"):
        # Logic to force download/upload artwork
        await callback_query.answer(text="⏳ تلاش مجدد با دانلود مستقیم...")
        etype, eid, cap = parts[1], int(parts[2]), ":".join(parts[3:])
        # Use artworkService logic to force it
        await artwork_service.force_manual_artwork(bot, chat_id, etype, eid, cap, user_id)
        await safe_delete(callback_query.message)

    # Retry logic
    elif data.startswith("retry:"):
        retry_data = data[6:]
        if retry_data.startswith("search_retry:"):
            _, t, term = retry_data.split(":", 2)
            await handle_search(bot, chat_id, user_id, t, term, api_client, search_cache_service, OFFLINE_MODE)
        elif retry_data.startswith("download_retry:"):
            _, tid = retry_data.split(":")
            if tid.isdigit(): tid = int(tid)
            settings = await user_settings_service.get_settings(user_id)
            quality_value = settings.download_quality.value
            if quality_value == "ask": quality_value = "192"
            status_msg, _ = await download_service.download_and_send_track(chat_id, tid, user_id, selected_quality=quality_value)
        await safe_delete(callback_query.message)

async def update_settings_msg(bot, message, user_id, user_settings_service):
    settings = await user_settings_service.get_settings(user_id)
    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"
    from core.config import BOT_NAME
    text = (
        f"⚙️ *پنل تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت جستجوی سریع:* {'✅ فعال' if settings.quick_mode else '❌ غیرفعال'}\n"
        f"🎵 *کیفیت پیش‌فرض:* {quality_text}\n"
        f"🖼️ *نمایش کاور آهنگ:* {'✅ فعال' if settings.show_artwork else '❌ غیرفعال'}\n"
        f"📥 *دانلود خودکار:* {'✅ فعال' if settings.auto_download else '❌ غیرفعال'}\n"
        f"🔔 *اعلان‌های سیستم:* {'✅ فعال' if settings.notifications else '❌ غیرفعال'}\n"
        f"\n💡 *راهنما:* برای تغییر هر مورد، روی دکمه مربوطه کلیک کنید."
    )
    markup = get_settings_keyboard(settings.quick_mode, quality_text, settings.show_artwork, settings.auto_download, settings.notifications)
    message = await edit_message(message, text, reply_markup=markup)
