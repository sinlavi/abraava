from bot.wrapper import BotClient, Message
from services.registration_service import UserRegistrationService
from services.membership_service import verify_all_memberships
from utils.parser import parse_search_query
from utils.messages import send_message, edit_message, safe_delete
from bot.handlers.commands import start_command, help_command, about_command
from bot.handlers.settings import settings_command, stats_command
from bot.handlers.search import handle_search, quick_search, ask_search_choice
from bot.handlers.details import show_track_page, show_collection_page, show_artist_page
from services.odesli_service import OdesliService
from core.config import OFFLINE_MODE
import re

async def handle_message_logic(bot: BotClient, msg_wrapped: Message, services: dict):
    user_id = msg_wrapped.author_id
    chat_id = msg_wrapped.chat_id
    text = msg_wrapped.text

    if not text: return

    # Clean RTL/LTR marks and whitespace
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text).strip()

    if not text.startswith("/"):
        if len(text) > 100:
            await msg_wrapped.reply("⚠️ *متن پیام خیلی طولانی است*\n\nحداکثر ۱۰۰ کاراکتر مجاز است.")
            return

    await services["registration_service"].register_user(msg_wrapped)

    if text.startswith("/start"):
        if len(text.split()) > 1:
            start_param = text.split()[1]
            if "_" in start_param:
                parts = start_param.split("_", 1)
                type_, item_id = parts[0], parts[1]
                if item_id.isdigit(): item_id = int(item_id)
                if type_ == "artist": await show_artist_page(bot, chat_id, item_id, 1, services["artwork_service"], user_id, reply_to=msg_wrapped.id)
                elif type_ == "collection": await show_collection_page(bot, chat_id, item_id, 1, services["artwork_service"], user_id, reply_to=msg_wrapped.id)
                elif type_ == "track": await show_track_page(bot, chat_id, item_id, services["artwork_service"], user_id, reply_to=msg_wrapped.id)
                return
        await start_command(bot, msg_wrapped)
        return

    is_member, missing = await verify_all_memberships(bot, user_id, services["api_client"])
    if not is_member:
        markup_rows = []
        channels_text = "⚠️ *برای استفاده از ربات باید در کانال‌های زیر عضو شوید:*"
        for ch in missing:
            name = ch.get('channel_name', ch.get('channel_username', ch.get('channel_id')))
            link = ch.get('invite_link', '')
            if link: markup_rows.append([{"text": f"📢 عضویت در {name}", "url": link}])
            else: channels_text += f"\n\n🔸 {name}"
        await send_message(bot, chat_id, channels_text, reply_markup=markup_rows)
        return

    if text.startswith("/help"): await help_command(bot, msg_wrapped)
    elif text.startswith("/settings"):
        if msg_wrapped.is_group: await msg_wrapped.reply("⚙️ تنظیمات فقط در پیوی در دسترس است.")
        else: await settings_command(bot, msg_wrapped, services["user_settings_service"])
    elif text.startswith("/stats"):
        if msg_wrapped.is_group: await msg_wrapped.reply("📊 آمار فقط در پیوی در دسترس است.")
        else: await stats_command(bot, msg_wrapped, services["api_client"], services["search_rate_limiter"], services["download_rate_limiter"])
    elif text.startswith("/about"): await about_command(bot, msg_wrapped)
    else:
        query = await parse_search_query(text)
        if query:
            type_, term = query
            if term is None:
                usage_map = {
                    "track": "🔍 *راهنمای جستجوی آهنگ:*\n\nکافیست نام آهنگ را مقابل دستور بنویسید.\nمثال: `/track محسن چاوشی`",
                    "album": "📀 *راهنمای جستجوی آلبوم:*\n\nکافیست نام آلبوم را مقابل دستور بنویسید.\nمثال: `/album ابراهیم`",
                    "artist": "🎤 *راهنمای جستجوی هنرمند:*\n\nکافیست نام هنرمند را مقابل دستور بنویسید.\nمثال: `/artist شادمهر عقیلی`",
                    "quick": "⚡ *راهنمای دانلود سریع:*\n\nکافیست نام آهنگ را مقابل دستور بنویسید تا اولین نتیجه مستقیما دانلود شود.\nمثال: `/quick آهنگ جدید`",
                    "ytm": "🎧 *راهنمای جستجو در یوتیوب موزیک:*\n\nکافیست نام آهنگ را مقابل دستور بنویسید.\nمثال: `/ytm shape of you`",
                    "sc": "☁️ *راهنمای جستجو در ساندکلاد:*\n\nکافیست نام آهنگ را مقابل دستور بنویسید.\nمثال: `/sc shadow of the day`"
                }
                await send_message(bot, chat_id, usage_map.get(type_, "⚠️ لطفا عبارت مورد نظر خود را وارد کنید."))
                return

            settings = await services["user_settings_service"].get_settings(user_id)
            if (type_ == "quick" or settings.quick_mode) and not msg_wrapped.is_group:
                await ask_search_choice(bot, chat_id, user_id, type_, term, is_quick=True, reply_to=msg_wrapped.id)
            elif type_ == "quick" or settings.quick_mode:
                await quick_search(bot, chat_id, user_id, term, services["api_client"], services["user_settings_service"], services["download_service"], reply_to=msg_wrapped.id)
            elif type_ == "itunes_track":
                await show_track_page(bot, chat_id, int(term), services["artwork_service"], user_id, reply_to=msg_wrapped.id)
            elif type_ == "itunes_album":
                await show_collection_page(bot, chat_id, int(term), 1, services["artwork_service"], user_id, reply_to=msg_wrapped.id)
            elif type_ == "itunes_artist":
                await show_artist_page(bot, chat_id, int(term), 1, services["artwork_service"], user_id, reply_to=msg_wrapped.id)
            elif type_ == "music_link":
                status_msg = await send_message(bot, chat_id, "🔍 *در حال بررسی پیوند...*", reply_to_message_id=msg_wrapped.id)
                resolved = await services["odesli_service"].resolve_link(term)
                if not resolved:
                    await edit_message(status_msg, "❌ متأسفانه اطلاعاتی برای این پیوند یافت نشد.")
                    return
                res_type, itunes_id = resolved.get("type"), resolved.get("itunes_id")
                if itunes_id:
                    if res_type == "track": await show_track_page(bot, chat_id, itunes_id, services["artwork_service"], user_id, message_to_edit=status_msg)
                    elif res_type == "collection": await show_collection_page(bot, chat_id, itunes_id, 1, services["artwork_service"], user_id, message_to_edit=status_msg)
                    elif res_type == "artist": await show_artist_page(bot, chat_id, itunes_id, 1, services["artwork_service"], user_id, message_to_edit=status_msg)
                else:
                    yt_url = resolved.get("youtube_url")
                    if yt_url:
                        m = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:&|\?|$)', yt_url)
                        if m: await show_track_page(bot, chat_id, f"yt_{m.group(1)}", services["artwork_service"], user_id, message_to_edit=status_msg)
                        else:
                            await safe_delete(status_msg)
                            await services["direct_download_service"].ask_confirmation(chat_id, yt_url, user_id=user_id)
                    else: await edit_message(status_msg, "❌ متأسفانه نسخه قابل دانلودی یافت نشد.")
            elif type_ == "direct_link":
                yt_m = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})', term)
                sc_m = re.search(r'soundcloud\.com\/([a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+)', term)
                if yt_m: await show_track_page(bot, chat_id, f"yt_{yt_m.group(1)}", services["artwork_service"], user_id, reply_to=msg_wrapped.id)
                elif sc_m: await show_track_page(bot, chat_id, f"sc_{sc_m.group(1)}", services["artwork_service"], user_id, reply_to=msg_wrapped.id)
                else: await services["direct_download_service"].ask_confirmation(chat_id, term, user_id=user_id, reply_to=msg_wrapped.id)
            elif type_ in ["track", "album", "artist", "ytm", "sc", "quick", "all"]:
                if not msg_wrapped.is_group: await ask_search_choice(bot, chat_id, user_id, type_, term, reply_to=msg_wrapped.id)
                else: await handle_search(bot, chat_id, user_id, type_, term, services["api_client"], services["search_cache_service"], OFFLINE_MODE, reply_to=msg_wrapped.id)
        else:
            if text.startswith("/"):
                await send_message(bot, chat_id, "⚠️ *دستور وارد شده معتبر نیست.*\n\nبرای مشاهده راهنما از /help استفاده کنید.")
            else:
                if not msg_wrapped.is_group: await ask_search_choice(bot, chat_id, user_id, "track", text, reply_to=msg_wrapped.id)
                else: await handle_search(bot, chat_id, user_id, "track", text, services["api_client"], services["search_cache_service"], OFFLINE_MODE, reply_to=msg_wrapped.id)
