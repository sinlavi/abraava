from balethon.objects import CallbackQuery, InlineKeyboard, InlineKeyboardButton
from models.schemas import DownloadQuality
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.search_results import send_search_results, send_external_search_results
from bot.handlers.album_download import download_album
from bot.handlers.search import handle_search, quick_search, PENDING_SEARCHES
from bot.handlers.preview import send_voice_preview
from bot.handlers.lyrics import handle_lyrics_request
import crawlers.utils
from bot.keyboards import get_settings_keyboard, get_quality_keyboard, get_confirmation_keyboard, create_close_button, get_my_hub_keyboard
from utils.messages import send_message, edit_message, safe_delete
from core.config import OFFLINE_MODE, DEEP_LINK_BASE
from core.logger import logger
import asyncio
import time

DIRECT_LINKS = {} # id -> url

async def store_direct_link(url: str) -> str:
    import uuid
    link_id = uuid.uuid4().hex[:10]
    DIRECT_LINKS[link_id] = url
    return link_id

async def handle_callback(bot, callback_query: CallbackQuery, api_client, user_settings_service,
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
        await bot.answer_callback_query(callback_query.id, text="⚠️ شما دسترسی به این پیام را ندارید. این پیام برای کاربر دیگری ساخته شده است.", show_alert=True)
        return

    # Use cleaned parts for the rest of the logic
    parts = new_parts
    data = ":".join(parts)

    if data == "close":
        await safe_delete(callback_query.message)
        return

    if data == "help_cmd":
        from bot.handlers.commands import help_command
        await help_command(bot, callback_query.message, is_callback=True)
        return

    if data == "ignore":
        await bot.answer_callback_query(callback_query.id, text="")
        return

    # Hub and Discovery Callbacks
    if data == "my_hub":
        text = "👤 *مرکز مدیریت شخصی کاربر*\n\nاز این بخش می‌توانید به کتابخانه، لیست‌های پخش شخصی، هنرمندان دنبال شده و تاریخچه پخش خود دسترسی داشته باشید."
        await edit_message(callback_query.message, text, reply_markup=get_my_hub_keyboard(user_id))
        return

    if data.startswith("my_lib"):
        res = await api_client.get_library(user_id)
        items = res.get("items", []) if res.get("success") else []
        text = "📌 *کتابخانه شخصی شما:*\n\n"
        markup = []
        if not items:
            text += "کتابخانه شما خالی است."
        else:
            for item in items[:15]:
                etype = item.get("entityType")
                eid = item.get("entityId")
                text += f"🔹 {etype}: `{eid}`\n"
                markup.append([InlineKeyboardButton(text=f"📂 مشاهده {etype} ({eid})", callback_data=f"{etype}:{eid}:u{user_id}")])
        markup.append([InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "create_pl_prompt":
        num_res = await api_client.get_my_playlists(user_id)
        count = len(num_res.get("playlists", [])) + 1 if num_res.get("success") else 1
        new_name = f"لیست پخش {count}"
        c_res = await api_client.create_playlist(user_id, name=new_name)
        if c_res.get("success"):
            await bot.answer_callback_query(callback_query.id, text=f"✅ لیست پخش '{new_name}' ساخته شد.")
        else:
            await bot.answer_callback_query(callback_query.id, text="⚠️ خطا در ساخت لیست پخش.", show_alert=True)

        res = await api_client.get_my_playlists(user_id)
        playlists = res.get("playlists", []) if res.get("success") else []
        text = "🎶 *لیست‌های پخش شما:*\n\n"
        markup = []
        for p in playlists:
            pid = p.get("playlistId")
            pname = p.get("name")
            tcount = p.get("trackCount", 0)
            text += f"🔹 *{pname}* ({tcount} آهنگ)\n"
            markup.append([InlineKeyboardButton(text=f"🎶 {pname} ({tcount} قطعه)", callback_data=f"view_pl:{pid}:u{user_id}")])
        markup.append([InlineKeyboardButton(text="➕ ساخت لیست پخش جدید", callback_data=f"create_pl_prompt:u{user_id}")])
        markup.append([InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "my_playlists":
        res = await api_client.get_my_playlists(user_id)
        playlists = res.get("playlists", []) if res.get("success") else []
        text = "🎶 *لیست‌های پخش شما:*\n\n"
        markup = []
        if not playlists:
            text += "شما هنوز هیچ لیست پخشی نساخته‌اید."
        else:
            for p in playlists:
                pid = p.get("playlistId")
                pname = p.get("name")
                tcount = p.get("trackCount", 0)
                text += f"🔹 *{pname}* ({tcount} آهنگ)\n"
                markup.append([InlineKeyboardButton(text=f"🎶 {pname} ({tcount} قطعه)", callback_data=f"view_pl:{pid}:u{user_id}")])
        markup.append([InlineKeyboardButton(text="➕ ساخت لیست پخش جدید", callback_data=f"create_pl_prompt:u{user_id}")])
        markup.append([InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "my_artists":
        res = await api_client.get_my_artists(user_id)
        artists = res.get("artists", []) if res.get("success") else []
        text = "🎤 *هنرمندان دنبال شده شما:*\n\n"
        markup = []
        if not artists:
            text += "شما هیچ هنرمندی را دنبال نکرده‌اید."
        else:
            for a in artists:
                aid = a.get("artistId")
                text += f"🎤 کد هنرمند: `{aid}`\n"
                markup.append([InlineKeyboardButton(text=f"🎤 هنرمند {aid}", callback_data=f"artist:{aid}:u{user_id}")])
        markup.append([InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "my_history":
        res = await api_client.get_history(user_id, limit=10)
        history = res.get("history", []) if res.get("success") else []
        text = "📜 *تاریخچه پخش شما:*\n\n"
        markup = []
        if not history:
            text += "تاریخچه‌ای یافت نشد."
        else:
            for i, item in enumerate(history, 1):
                tid = item.get("trackId")
                text += f"{i}. آهنگ `{tid}`\n"
                markup.append([InlineKeyboardButton(text=f"🎵 آهنگ {tid}", callback_data=f"track:{tid}:u{user_id}")])
            markup.append([InlineKeyboardButton(text="🗑️ پاک‌سازی تاریخچه", callback_data=f"clear_history_prompt:u{user_id}")])
        markup.append([InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "clear_history_prompt":
        text = "❓ *آیا از پاک‌سازی تمام تاریخچه پخش خود اطمینان دارید؟*"
        markup = [
            [InlineKeyboardButton(text="✅ بله، پاک شود", callback_data=f"confirm_clear_history:u{user_id}"),
             InlineKeyboardButton(text="❌ انصراف", callback_data=f"my_history:u{user_id}")]
        ]
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "confirm_clear_history":
        await api_client.clear_history(user_id)
        await bot.answer_callback_query(callback_query.id, text="✅ تاریخچه با موفقیت پاک شد.")
        text = "📜 تاریخچه پخش شما پاک شد."
        markup = [[InlineKeyboardButton(text="🔙 بازگشت به هاب شخصی", callback_data=f"my_hub:u{user_id}")]]
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "popular_tracks":
        res = await api_client.get_popular(limit=10)
        tracks = res.get("results", []) if res.get("success") else []
        text = "🔥 *محبوب‌ترین آهنگ‌ها:*\n\n"
        markup = []
        for i, t in enumerate(tracks, 1):
            tid = t.get("trackId")
            tname = t.get("trackName", "نامشخص")
            aname = t.get("artistName", "نامشخص")
            text += f"{i}. {tname} - {aname}\n"
            markup.append([InlineKeyboardButton(text=f"{i}. {tname[:28]}", callback_data=f"track:{tid}:u{user_id}")])
        markup.append([create_close_button(user_id)])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data == "fresh_tracks":
        res = await api_client.get_fresh(limit=10)
        tracks = res.get("results", []) if res.get("success") else []
        text = "🆕 *تازه‌ترین آهنگ‌های اضافه شده:*\n\n"
        markup = []
        for i, t in enumerate(tracks, 1):
            tid = t.get("trackId")
            tname = t.get("trackName", "نامشخص")
            aname = t.get("artistName", "نامشخص")
            text += f"{i}. {tname} - {aname}\n"
            markup.append([InlineKeyboardButton(text=f"{i}. {tname[:28]}", callback_data=f"track:{tid}:u{user_id}")])
        markup.append([create_close_button(user_id)])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    # Social Interaction Callbacks
    if data.startswith("like_toggle:"):
        etype, eid = parts[1], parts[2]
        status = await api_client.get_like_status(etype, eid, user_id)
        if status.get("liked"):
            await api_client.unlike_entity(user_id, etype, eid)
            await bot.answer_callback_query(callback_query.id, text="💔 از پسندیده‌ها حذف شد.")
        else:
            await api_client.like_entity(user_id, etype, eid)
            await bot.answer_callback_query(callback_query.id, text="❤️ پسندیده شد!")

        # Refresh page
        if etype == "track": await show_track_page(bot, chat_id, eid, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        elif etype == "collection": await show_collection_page(bot, chat_id, eid, 1, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        return

    if data.startswith("lib_toggle:"):
        etype, eid = parts[1], parts[2]
        lib_res = await api_client.get_library(user_id, etype)
        lib_ids = [str(x.get("entityId")) for x in lib_res.get("items", [])] if lib_res.get("success") else []
        if str(eid) in lib_ids:
            await api_client.remove_from_library(user_id, etype, eid)
            await bot.answer_callback_query(callback_query.id, text="🗑️ از کتابخانه حذف شد.")
        else:
            await api_client.save_to_library(user_id, etype, eid)
            await bot.answer_callback_query(callback_query.id, text="📌 به کتابخانه شما اضافه شد.")

        if etype == "track": await show_track_page(bot, chat_id, eid, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        elif etype == "collection": await show_collection_page(bot, chat_id, eid, 1, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        return

    if data.startswith("follow_artist_toggle:"):
        aid = parts[1]
        res = await api_client.get_my_artists(user_id)
        followed_ids = [str(a.get("artistId")) for a in res.get("artists", [])] if res.get("success") else []
        if str(aid) in followed_ids:
            await api_client.unfollow_artist(user_id, aid)
            await bot.answer_callback_query(callback_query.id, text="➖ هنرمند از لیست دنبال‌شده‌ها حذف شد.")
        else:
            await api_client.follow_artist(user_id, aid)
            await bot.answer_callback_query(callback_query.id, text="➕ هنرمند به لیست دنبال‌شده‌ها اضافه شد.")

        await show_artist_page(bot, chat_id, aid, 1, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        return

    if data.startswith("artist_tracks:"):
        aid = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 1
        res = await api_client.get_artist_tracks(aid, page=page, limit=10)
        tracks = res.get("results", []) if res.get("success") else []
        total = res.get("total", len(tracks))
        text = f"🎤 *تمام آهنگ‌های هنرمند (مجموع {total} قطعه):*\n\n"
        markup = []
        for i, t in enumerate(tracks, 1):
            tid = t.get("trackId")
            tname = t.get("trackName", "نامشخص")
            text += f"{i}. {tname}\n"
            markup.append([InlineKeyboardButton(text=f"{i}. {tname[:30]} 🎵", callback_data=f"track:{tid}:u{user_id}")])

        pages = res.get("pages", 1)
        if pages > 1:
            from bot.keyboards import create_pagination_row
            pag_row = create_pagination_row(f"artist_tracks:{aid}", page, pages, user_id=user_id)
            if pag_row: markup.append(pag_row)

        markup.append([InlineKeyboardButton(text="🔙 بازگشت به صفحه هنرمند", callback_data=f"artist:{aid}:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data.startswith("add_to_pl:"):
        track_id = parts[1]
        res = await api_client.get_my_playlists(user_id)
        playlists = res.get("playlists", []) if res.get("success") else []
        text = "➕ *انتخاب لیست پخش برای افزودن آهنگ:*\n\n"
        markup = []
        if not playlists:
            text += "شما هنوز هیچ لیست پخشی نساخته‌اید."
        else:
            for p in playlists:
                pid = p.get("playlistId")
                pname = p.get("name")
                markup.append([InlineKeyboardButton(text=f"🎶 {pname}", callback_data=f"pl_add_track:{pid}:{track_id}:u{user_id}")])

        markup.append([InlineKeyboardButton(text="🔙 بازگشت به آهنگ", callback_data=f"track:{track_id}:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data.startswith("pl_add_track:"):
        pid, track_id = parts[1], parts[2]
        res = await api_client.add_track_to_playlist(user_id, pid, track_id)
        if res.get("success"):
            await bot.answer_callback_query(callback_query.id, text="✅ آهنگ به لیست پخش اضافه شد.")
        else:
            await bot.answer_callback_query(callback_query.id, text=f"⚠️ {res.get('message', 'خطا در افزودن')}", show_alert=True)
        await show_track_page(bot, chat_id, track_id, artwork_service, user_id, message_to_edit=callback_query.message, api_client=api_client)
        return

    if data.startswith("view_pl:"):
        pid = parts[1]
        pl_res = await api_client.get_playlist(pid)
        pl = pl_res.get("playlist", {}) if pl_res.get("success") else {}
        tracks_res = await api_client.get_playlist_tracks(pid)
        tracks = tracks_res.get("tracks", []) if tracks_res.get("success") else []

        pname = pl.get("name", "لیست پخش")
        text = f"🎶 *لیست پخش:* {pname}\n"
        if pl.get("description"): text += f"📝 {pl.get('description')}\n"
        text += f"\n🎵 *قطعات ({len(tracks)} مورد):*\n"

        markup = []
        for i, t in enumerate(tracks, 1):
            tid = t.get("trackId")
            tname = t.get("trackName", f"آهنگ {tid}")
            text += f"{i}. {tname}\n"
            markup.append([InlineKeyboardButton(text=f"{i}. {tname[:30]} 🎵", callback_data=f"track:{tid}:u{user_id}")])

        markup.append([InlineKeyboardButton(text="🔙 بازگشت به لیست‌های پخش", callback_data=f"my_playlists:u{user_id}")])
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
        return

    if data.startswith("comments:"):
        etype, eid = parts[1], parts[2]
        res = await api_client.get_comments(etype, eid)
        comments = res.get("comments", []) if res.get("success") else []
        text = f"💬 *نظرات کاربران:*\n\n"
        if not comments:
            text += "هنوز نظری ثبت نشده است."
        else:
            for c in comments[:10]:
                uname = c.get("displayName") or c.get("username") or "کاربر"
                cbody = c.get("content", "")
                text += f"👤 *{uname}:* {cbody}\n\n"

        markup = [
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"{etype}:{eid}:u{user_id}")]
        ]
        await edit_message(callback_query.message, text, reply_markup=InlineKeyboard(*markup))
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
            await bot.answer_callback_query(callback_query.id, text="⬇️ در حال دانلود...")
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
            await bot.answer_callback_query(callback_query.id, text="✅ تنظیمات ذخیره شد")
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
        await bot.answer_callback_query(callback_query.id, text=f"✅ کیفیت به {q} تغییر یافت")
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
        is_pag = (len(parts) > 2 and parts[2].isdigit())
        msg_to_edit = callback_query.message if is_pag else None
        await show_artist_page(bot, chat_id, artist_id, page, artwork_service, user_id, msg_to_edit, is_pagination=is_pag, api_client=api_client)
    elif data.startswith("collection:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        page = int(parts[2]) if len(parts) > 2 else 1
        is_pag = (len(parts) > 2 and parts[2].isdigit())
        msg_to_edit = callback_query.message if is_pag else None
        await show_collection_page(bot, chat_id, coll_id, page, artwork_service, user_id, msg_to_edit, is_pagination=is_pag, api_client=api_client)
    elif data.startswith("track:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await show_track_page(bot, chat_id, track_id, artwork_service, user_id, api_client=api_client)
    elif data.startswith("single_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        tracks_data = await crawlers.utils.get_or_crawl_collection_tracks(coll_id)
        if tracks_data and tracks_data.get("results"):
            track_id = tracks_data["results"][0].get("trackId")
            if track_id: await show_track_page(bot, chat_id, track_id, artwork_service, user_id, api_client=api_client)
            else: await bot.answer_callback_query(callback_query.id, text="❌ خطایی رخ داد", show_alert=True)
    elif data.startswith("recrawl:"):
        type_, eid = parts[1], parts[2]
        if eid.isdigit(): eid = int(eid)
        if type_ == "artist": await show_artist_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True, api_client=api_client)
        elif type_ == "collection": await show_collection_page(bot, chat_id, eid, 1, artwork_service, user_id, callback_query.message, force=True, api_client=api_client)

    elif data.startswith("lyrics:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await handle_lyrics_request(bot, chat_id, track_id, user_id, message_to_edit=None)
        await bot.answer_callback_query(callback_query.id, text="")

    # Searches
    elif data.startswith("page:search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_search_results(bot, chat_id, type_, cached["term"], cached["results"], page,
                                     search_cache_service, user_id, callback_query.message)
        else:
            await bot.answer_callback_query(callback_query.id, text="جستجو منقضی شده است", show_alert=True)
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
            await bot.answer_callback_query(callback_query.id, text="❌ پیوند منقضی شده است", show_alert=True)
        await safe_delete(callback_query.message)

    elif data.startswith("page:ext_search:"):
        search_id, type_, page = parts[2], parts[3], int(parts[4])
        cached = await search_cache_service.get(search_id)
        if cached:
            await send_external_search_results(bot, chat_id, type_, cached["term"], cached["results"]["results"], page,
                                              search_cache_service, user_id, callback_query.message)
        else:
            await bot.answer_callback_query(callback_query.id, text="جستجو منقضی شده است", show_alert=True)

    elif data.startswith("search_chat:"):
        query_id = parts[1]
        search_info = PENDING_SEARCHES.pop(query_id, None)
        if search_info:
            await safe_delete(callback_query.message)
            type_, term = search_info["type"], search_info["term"]
            is_quick, reply_to = search_info["is_quick"], search_info["reply_to"]

            if is_quick:
                await quick_search(bot, chat_id, user_id, term, api_client, user_settings_service, download_service, reply_to=reply_to)
            else:
                await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE, reply_to=reply_to)
        else:
            await bot.answer_callback_query(callback_query.id, text="⚠️ این درخواست منقضی شده است.", show_alert=True)

    # Downloads
    elif data.startswith("download:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        settings = await user_settings_service.get_settings(user_id)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [
                [InlineKeyboardButton(text="🎵 ۳۲۰ kbps", callback_data=f"dl_q:320:{track_id}:u{user_id}")],
                [InlineKeyboardButton(text="🎶 ۱۹۲ kbps", callback_data=f"dl_q:192:{track_id}:u{user_id}")],
                [InlineKeyboardButton(text="🎧 ۱۲۸ kbps", callback_data=f"dl_q:128:{track_id}:u{user_id}")],
                [create_close_button(user_id)]
            ]
            await send_message(bot, chat_id, "🎵 *کیفیت دانلود را انتخاب کنید:*", reply_markup=InlineKeyboard(*markup))
        else:
            await bot.answer_callback_query(callback_query.id, text="⏳ در حال آماده‌سازی...")
            status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود...*", show_cancel=True)
            status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, status_msg=status_msg)

    elif data.startswith("dl_q:"):
        quality, track_id = parts[1], parts[2]
        if track_id.isdigit(): track_id = int(track_id)
        await bot.answer_callback_query(callback_query.id, text=f"⏳ دانلود با کیفیت {quality}...")
        status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, selected_quality=quality, status_msg=callback_query.message)

    elif data.startswith("dl_fb:"):
        quality, track_id = parts[1], parts[2]
        if track_id.isdigit(): track_id = int(track_id)
        await bot.answer_callback_query(callback_query.id, text=f"⏳ دانلود با کیفیت {quality}...")
        status_msg, _ = await download_service.download_and_send_track(chat_id, track_id, user_id, selected_quality=quality, status_msg=callback_query.message, skip_size_check=True)

    elif data.startswith("preview:"):
        track_id = parts[1]
        if track_id.isdigit(): track_id = int(track_id)
        await bot.answer_callback_query(callback_query.id, text="⏳ در حال دریافت...")
        asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
    elif data.startswith("download_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        settings = await user_settings_service.get_settings(user_id)
        if settings.download_quality == DownloadQuality.ASK:
            markup = [
                [InlineKeyboardButton(text="🎵 ۳۲۰ kbps", callback_data=f"dl_aq:320:{coll_id}:u{user_id}")],
                [InlineKeyboardButton(text="🎶 ۱۹۲ kbps", callback_data=f"dl_aq:192:{coll_id}:u{user_id}")],
                [InlineKeyboardButton(text="🎧 ۱۲۸ kbps", callback_data=f"dl_aq:128:{coll_id}:u{user_id}")],
                [create_close_button(user_id)]
            ]
            await send_message(bot, chat_id, "📀 *کیفیت دانلود آلبوم را انتخاب کنید:*", reply_markup=InlineKeyboard(*markup))
        else:
            await bot.answer_callback_query(callback_query.id, text="📀 شروع دانلود آلبوم...")
            status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود آلبوم...*", show_cancel=True)
            asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service, status_msg=status_msg))

    elif data.startswith("dl_aq:"):
        quality, coll_id = parts[1], parts[2]
        if coll_id.isdigit(): coll_id = int(coll_id)
        await bot.answer_callback_query(callback_query.id, text=f"📀 شروع دانلود با کیفیت {quality}...")
        asyncio.create_task(download_album(bot, chat_id, coll_id, user_id, download_service, quality=quality, status_msg=callback_query.message))

    elif data.startswith("retry_failed:"):
        failed_ids = parts[1].split(",")
        await bot.answer_callback_query(callback_query.id, text="🔄 تلاش مجدد برای قطعات ناموفق...")
        settings = await user_settings_service.get_settings(user_id)
        quality_value = settings.download_quality.value
        if quality_value == "ask": quality_value = "192"
        asyncio.create_task(download_album(bot, chat_id, None, user_id, download_service, quality=quality_value, status_msg=callback_query.message, retry_ids=failed_ids))

    elif data.startswith("cancel_album:"):
        coll_id = parts[1]
        if coll_id.isdigit(): coll_id = int(coll_id)
        download_service.album_tracker.cancel_download(user_id, coll_id)
        await bot.answer_callback_query(callback_query.id, text="⏹️ توقف دانلود...")

    elif data.startswith("force_artwork:"):
        await bot.answer_callback_query(callback_query.id, text="⏳ تلاش مجدد با دانلود مستقیم...")
        etype, eid, cap = parts[1], int(parts[2]), ":".join(parts[3:])
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
