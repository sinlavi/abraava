from core.config import OFFLINE_MODE
from core.logger import logger
from utils.messages import edit_message, safe_delete, send_message
from models.schemas import DownloadQuality
from bot.keyboards import get_settings_keyboard, get_quality_keyboard, create_close_button
from bot.handlers.commands import help_command
from bot.handlers.search import handle_search, quick_search, PENDING_SEARCHES
from bot.handlers.search_results import send_search_results, send_external_search_results
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.lyrics import handle_lyrics_request
from bot.handlers.preview import send_voice_preview
from bot.handlers.album_download import download_album
import asyncio

DIRECT_LINKS = {}

async def handle_callback(bot, callback_query, api_client, user_settings_service, artwork_service, search_cache_service, download_service, rate_limiter, download_rate_limiter, direct_download_service):
    data, chat_id, user_id, parts = callback_query.data, callback_query.message.chat_id, callback_query.author_id, callback_query.data.split(":")
    if ":u" in data:
        try:
            if int(data.split(":u")[1]) != user_id: await callback_query.answer("⚠️ این دکمه برای شما نیست.", show_alert=True); return
        except: pass
    if data.startswith("close"): await safe_delete(callback_query.message); await callback_query.answer()
    elif data.startswith("help_cmd"): await help_command(bot, callback_query.message, is_callback=True); await callback_query.answer()
    elif data.startswith("settings_cmd"): await update_settings_msg(bot, callback_query.message, user_id, user_settings_service); await callback_query.answer()
    elif data.startswith("menu_"):
        setting, settings = data.replace("menu_", "").split(":")[0], await user_settings_service.get_settings(user_id)
        current_val = getattr(settings, setting)
        if isinstance(current_val, bool): await user_settings_service.update_setting(user_id, setting, not current_val); await update_settings_msg(bot, callback_query.message, user_id, user_settings_service); await callback_query.answer("✅ تغییر اعمال شد.")
        else: await callback_query.answer()
    elif data.startswith("show_quality_menu"):
        settings = await user_settings_service.get_settings(user_id)
        await edit_message(callback_query.message, "🎵 *انتخاب کیفیت پیش‌فرض دانلود:*", reply_markup=get_quality_keyboard(settings.download_quality, user_id=user_id)); await callback_query.answer()
    elif data.startswith("set_quality:"): await user_settings_service.update_setting(user_id, "download_quality", parts[1]); await update_settings_msg(bot, callback_query.message, user_id, user_settings_service); await callback_query.answer(f"✅ کیفیت روی {parts[1]} تنظیم شد.")
    elif data.startswith("back_to_settings"): await update_settings_msg(bot, callback_query.message, user_id, user_settings_service); await callback_query.answer()
    elif data.startswith("artist:"): await show_artist_page(bot, chat_id, int(parts[1]), int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1, artwork_service, user_id, callback_query.message, is_pagination=True); await callback_query.answer()
    elif data.startswith("collection:"): await show_collection_page(bot, chat_id, int(parts[1]), int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1, artwork_service, user_id, callback_query.message, is_pagination=True); await callback_query.answer()
    elif data.startswith("track:") or data.startswith("single_album:"):
        tid = parts[1]
        if tid.isdigit(): tid = int(tid)
        await show_track_page(bot, chat_id, tid, artwork_service, user_id, callback_query.message); await callback_query.answer()
    elif data.startswith("recrawl:"):
        if parts[1] == "artist": await show_artist_page(bot, chat_id, int(parts[2]), 1, artwork_service, user_id, callback_query.message, force=True)
        elif parts[1] == "collection": await show_collection_page(bot, chat_id, int(parts[2]), 1, artwork_service, user_id, callback_query.message, force=True)
    elif data.startswith("lyrics:"):
        tid = parts[1]
        if tid.isdigit(): tid = int(tid)
        await handle_lyrics_request(bot, chat_id, tid, user_id, message_to_edit=None); await callback_query.answer()
    elif data.startswith("page:search:"):
        cached = await search_cache_service.get(parts[2])
        if cached: await send_search_results(bot, chat_id, parts[3], cached["term"], cached["results"], int(parts[4]), search_cache_service, user_id, callback_query.message)
        else: await callback_query.answer("جستجو منقضی شده است", show_alert=True)
    elif data.startswith("refine:"): await handle_search(bot, chat_id, user_id, parts[1], ":".join(parts[2:]), api_client, search_cache_service, OFFLINE_MODE)
    elif data.startswith("ext_dl:"):
        url = DIRECT_LINKS.get(parts[1])
        if url: await direct_download_service.ask_confirmation(chat_id, url, user_id=user_id)
        else: await callback_query.answer("❌ پیوند منقضی شده است", show_alert=True)
        await safe_delete(callback_query.message)
    elif data.startswith("page:ext_search:"):
        cached = await search_cache_service.get(parts[2])
        if cached: await send_external_search_results(bot, chat_id, parts[3], cached["term"], cached["results"]["results"], int(parts[4]), search_cache_service, user_id, callback_query.message)
        else: await callback_query.answer("جستجو منقضی شده است", show_alert=True)
    elif data.startswith("search_chat:"):
        search_info = PENDING_SEARCHES.pop(parts[1], None)
        if search_info:
            await safe_delete(callback_query.message)
            if search_info["is_quick"]: await quick_search(bot, chat_id, user_id, search_info["term"], api_client, user_settings_service, download_service, reply_to=search_info["reply_to"])
            else: await handle_search(bot, chat_id, user_id, search_info["type"], search_info["term"], api_client, search_cache_service, OFFLINE_MODE, reply_to=search_info["reply_to"])
        else: await callback_query.answer("⚠️ این درخواست منقضی شده است.", show_alert=True)
    elif data.startswith("download:"):
        tid, settings = parts[1], await user_settings_service.get_settings(user_id)
        if tid.isdigit(): tid = int(tid)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [[{"text": "🎵 ۳۲۰ kbps", "callback_data": f"dl_q:320:{tid}:u{user_id}"}], [{"text": "🎶 ۱۹۲ kbps", "callback_data": f"dl_q:192:{tid}:u{user_id}"}], [{"text": "🎧 ۱۲۸ kbps", "callback_data": f"dl_q:128:{tid}:u{user_id}"}], [create_close_button(user_id)]]
            await send_message(bot, chat_id, "🎵 *کیفیت دانلود را انتخاب کنید:*", reply_markup=markup)
        else:
            await callback_query.answer("⏳ در حال آماده‌سازی..."); status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود...*", show_cancel=True)
            await download_service.download_and_send_track(chat_id, tid, user_id, status_msg=status_msg)
    elif data.startswith("dl_q:"):
        tid = parts[2]
        if tid.isdigit(): tid = int(tid)
        await callback_query.answer(f"⏳ دانلود با کیفیت {parts[1]}..."); await download_service.download_and_send_track(chat_id, tid, user_id, selected_quality=parts[1], status_msg=callback_query.message)
    elif data.startswith("dl_fb:"):
        tid = parts[2]
        if tid.isdigit(): tid = int(tid)
        await callback_query.answer(f"⏳ دانلود با کیفیت {parts[1]}..."); await download_service.download_and_send_track(chat_id, tid, user_id, selected_quality=parts[1], status_msg=callback_query.message, skip_size_check=True)
    elif data.startswith("preview:"):
        tid = parts[1]
        if tid.isdigit(): tid = int(tid)
        await callback_query.answer("⏳ در حال دریافت..."); asyncio.create_task(send_voice_preview(bot, chat_id, tid, user_id))
    elif data.startswith("download_album:"):
        cid, settings = parts[1], await user_settings_service.get_settings(user_id)
        if cid.isdigit(): cid = int(cid)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [[{"text": "🎵 ۳۲۰ kbps", "callback_data": f"dl_aq:320:{cid}:u{user_id}"}], [{"text": "🎶 ۱۹۲ kbps", "callback_data": f"dl_aq:192:{cid}:u{user_id}"}], [{"text": "🎧 ۱۲۸ kbps", "callback_data": f"dl_aq:128:{cid}:u{user_id}"}], [create_close_button(user_id)]]
            await send_message(bot, chat_id, "📀 *کیفیت دانلود آلبوم را انتخاب کنید:*", reply_markup=markup)
        else:
            await callback_query.answer("📀 شروع دانلود آلبوم..."); status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود آلبوم...*", show_cancel=True)
            asyncio.create_task(download_album(bot, chat_id, cid, user_id, download_service, status_msg=status_msg))
    elif data.startswith("dl_aq:"):
        cid = parts[2]
        if cid.isdigit(): cid = int(cid)
        await callback_query.answer(f"📀 شروع دانلود با کیفیت {parts[1]}..."); asyncio.create_task(download_album(bot, chat_id, cid, user_id, download_service, quality=parts[1], status_msg=callback_query.message))
    elif data.startswith("retry_failed:"):
        await callback_query.answer("🔄 تلاش مجدد برای قطعات ناموفق..."); settings = await user_settings_service.get_settings(user_id)
        quality_value = settings.download_quality.value if settings.download_quality.value != "ask" else "192"
        asyncio.create_task(download_album(bot, chat_id, None, user_id, download_service, quality=quality_value, status_msg=callback_query.message, retry_ids=parts[1].split(",")))
    elif data.startswith("cancel_album:"):
        cid = parts[1]
        if cid.isdigit(): cid = int(cid)
        download_service.album_tracker.cancel_download(user_id, cid); await callback_query.answer("⏹️ توقف دانلود...")
    elif data.startswith("force_artwork:"):
        await callback_query.answer("⏳ تلاش مجدد با دانلود مستقیم..."); await artwork_service.force_manual_artwork(bot, chat_id, parts[1], int(parts[2]), ":".join(parts[3:]), user_id); await safe_delete(callback_query.message)
    elif data.startswith("retry:"):
        rd = data[6:]
        if rd.startswith("search_retry:"):
            _, t, term = rd.split(":", 2)
            await handle_search(bot, chat_id, user_id, t, term, api_client, search_cache_service, OFFLINE_MODE)
        elif rd.startswith("download_retry:"):
            tid = rd.split(":")[1]
            if tid.isdigit(): tid = int(tid)
            settings = await user_settings_service.get_settings(user_id)
            await download_service.download_and_send_track(chat_id, tid, user_id, selected_quality=settings.download_quality.value if settings.download_quality.value != "ask" else "192")
        await safe_delete(callback_query.message); await callback_query.answer()

async def update_settings_msg(bot, message, user_id, user_settings_service):
    settings = await user_settings_service.get_settings(user_id)
    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"
    from core.config import BOT_NAME
    text = f"⚙️ *پنل تنظیمات ربات {BOT_NAME}*\n\n⚡ *حالت جستجوی سریع:* {'✅ فعال' if settings.quick_mode else '❌ غیرفعال'}\n🎵 *کیفیت پیش‌فرض:* {quality_text}\n🖼️ *نمایش کاور آهنگ:* {'✅ فعال' if settings.show_artwork else '❌ غیرفعال'}\n📥 *دانلود خودکار:* {'✅ فعال' if settings.auto_download else '❌ غیرفعال'}\n🔔 *اعلان‌های سیستم:* {'✅ فعال' if settings.notifications else '❌ غیرفعال'}\n\n💡 *راهنما:* برای تغییر هر مورد، روی دکمه مربوطه کلیک کنید."
    await edit_message(message, text, reply_markup=get_settings_keyboard(settings.quick_mode, quality_text, settings.show_artwork, settings.auto_download, settings.notifications, user_id=user_id))
