from core.config import BOT_TOKEN, INFO_CHANNEL_ID, OFFLINE_MODE, API_BASE_URL, API_TOKEN
from balethon import Client
from balethon.objects import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboard
from core.logger import logger
from core.http_client import HttpClient

from services.api_client import APIClient
from services.user_settings_service import UserSettingsService
from services.artwork_service import ArtworkService
from services.search_cache_service import search_cache_service
from services.rate_limiter import RateLimiter, DownloadRateLimiter
from services.tracker import AlbumDownloadTracker
from services.tagging_service import TaggingService
from services.error_notifier import BaleUploadErrorNotifier
from services.download_service import DownloadService
from services.membership_service import verify_all_memberships
from services.registration_service import UserRegistrationService
from services.direct_download_service import DirectDownloadService
from services.odesli_service import OdesliService

from bot.handlers.commands import start_command, help_command, about_command
from bot.handlers.settings import settings_command, stats_command
from bot.handlers.search import handle_search, quick_search
from bot.handlers.callbacks import handle_callback
from bot.handlers.broadcast import process_broadcast_message
from bot.handlers.details import show_track_page, show_collection_page, show_artist_page
from utils.parser import parse_search_query
from utils.messages import send_message, edit_message, safe_delete
from utils.validation import is_valid_message

import asyncio
import signal
import sys
import time
import re

# Initialize Services
api_client = APIClient(API_BASE_URL, API_TOKEN)
user_settings_service = UserSettingsService(api_client)
registration_service = UserRegistrationService(api_client, user_settings_service)
artwork_service = ArtworkService(api_client, user_settings_service)
rate_limiter = RateLimiter()
download_rate_limiter = DownloadRateLimiter()
album_tracker = AlbumDownloadTracker(api_client)
tagging_service = TaggingService()
error_notifier = BaleUploadErrorNotifier(api_client)

bot = Client(token=BOT_TOKEN)
download_service = DownloadService(bot, api_client, user_settings_service, artwork_service,
                                   tagging_service, error_notifier, album_tracker, download_rate_limiter)
direct_download_service = DirectDownloadService(bot, tagging_service)

@bot.on_initialize()
async def on_init():
    logger.info(f"Bot initialized. Offline Mode: {OFFLINE_MODE}")

@bot.on_shutdown()
async def on_shutdown():
    await HttpClient.close()
    logger.info("Bot shutting down...")

@bot.on_message()
async def on_message(message: Message):
    if not message.author or message.author.is_bot: return

    # Broadcast forward handling
    if message.chat.type == "channel" and str(message.chat.id) == str(INFO_CHANNEL_ID):
        await process_broadcast_message(bot, message, api_client)
        return

    user_id = message.author.id
    chat_id = message.chat.id
    text = message.content or ""

    # Register user
    await registration_service.register_user(message)

    if message.chat.type == "channel": return

    is_group = message.chat.type in ["group", "supergroup"]
    if is_group:
        bot_username = bot.user.username
        is_reply_to_bot = message.reply_to_message and message.reply_to_message.author.id == bot.user.id
        is_mentioned = f"@{bot_username}" in text

        if not (is_mentioned or is_reply_to_bot):
            return

        if not is_valid_message(message): return
        text = re.sub(rf"@{re.escape(bot_username)}\s*", "", text).strip()

        if len(text) > 100:
            await message.reply("⚠️ *متن پیام خیلی طولانی است*\n\nحداکثر ۱۰۰ کاراکتر مجاز است.")
            return

    # Membership check
    if not text.startswith("/start"):
        is_member, missing = await verify_all_memberships(bot, user_id, api_client)
        if not is_member:
            markup_rows = []
            channels_text = "⚠️ *برای استفاده از ربات باید در کانال‌های زیر عضو شوید:*"
            from bot.keyboards import create_close_button
            for ch in missing:
                name = ch.get('channel_name', ch.get('channel_username', ch.get('channel_id')))
                link = ch.get('invite_link', '')
                if link:
                    markup_rows.append([InlineKeyboardButton(text=f"📢 عضویت در {name}", url=link)])
                else:
                    channels_text += f"\n\n🔸 {name}"
            markup_rows.append([create_close_button(user_id)])
            await send_message(bot, chat_id, channels_text, reply_markup=InlineKeyboard(*markup_rows), user_id=user_id)
            return

    if text.startswith("/start"):
        # Deep link handling
        if len(text.split()) > 1:
            start_param = text.split()[1]
            if "_" in start_param:
                type_, item_id = start_param.split("_", 1)
                if item_id.isdigit(): item_id = int(item_id)
                if type_ == "artist": await show_artist_page(bot, chat_id, item_id, 1, artwork_service, user_id)
                elif type_ == "collection": await show_collection_page(bot, chat_id, item_id, 1, artwork_service, user_id)
                elif type_ == "track": await show_track_page(bot, chat_id, item_id, artwork_service, user_id)
                return
        await start_command(bot, message)
    elif text.startswith("/help"):
        await help_command(bot, message)
    elif text.startswith("/settings"):
        if is_group: await message.reply("⚙️ تنظیمات فقط در پیوی در دسترس است.")
        else: await settings_command(bot, message, user_settings_service)
    elif text.startswith("/stats"):
        if is_group: await message.reply("📊 آمار فقط در پیوی در دسترس است.")
        else: await stats_command(bot, message, api_client, rate_limiter, download_rate_limiter)
    elif text.startswith("/about"):
        await about_command(bot, message)
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
                await send_message(bot, chat_id, usage_map.get(type_, "⚠️ لطفا عبارت مورد نظر خود را وارد کنید."), user_id=user_id)
                return

            settings = await user_settings_service.get_settings(user_id)
            if type_ == "quick" or settings.quick_mode:
                await quick_search(bot, chat_id, user_id, term, api_client, user_settings_service, download_service)
            elif type_ == "itunes_track":
                await show_track_page(bot, chat_id, int(term), artwork_service, user_id)
            elif type_ == "itunes_album":
                await show_collection_page(bot, chat_id, int(term), 1, artwork_service, user_id)
            elif type_ == "itunes_artist":
                await show_artist_page(bot, chat_id, int(term), 1, artwork_service, user_id)
            elif type_ == "music_link":
                status_msg = await send_message(bot, chat_id, "🔍 *در حال بررسی پیوند...*", user_id=user_id)
                resolved = await OdesliService.resolve_link(term)
                if not resolved:
                    status_msg = await edit_message(status_msg, "❌ متأسفانه اطلاعاتی برای این پیوند یافت نشد.", user_id=user_id)
                    return

                res_type = resolved.get("type")
                itunes_id = resolved.get("itunes_id")

                if itunes_id:
                    if res_type == "track":
                        await show_track_page(bot, chat_id, itunes_id, artwork_service, user_id, message_to_edit=status_msg)
                    elif res_type == "collection":
                        await show_collection_page(bot, chat_id, itunes_id, 1, artwork_service, user_id, message_to_edit=status_msg)
                    elif res_type == "artist":
                        await show_artist_page(bot, chat_id, itunes_id, 1, artwork_service, user_id, message_to_edit=status_msg)
                else:
                    # No iTunes ID found, try fallback to YouTube/YouTube Music
                    yt_url = resolved.get("youtube_url")
                    if yt_url:
                        # Extract video ID if possible for show_track_page
                        m = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:&|\?|$)', yt_url)
                        if m:
                            await show_track_page(bot, chat_id, f"yt_{m.group(1)}", artwork_service, user_id, message_to_edit=status_msg)
                        else:
                            await safe_delete(status_msg)
                            await direct_download_service.ask_confirmation(chat_id, yt_url, user_id=user_id)
                    else:
                        # No link at all, try searching
                        title, artist = resolved.get("title"), resolved.get("artist")
                        if title and artist:
                            status_msg = await edit_message(status_msg, f"🔍 *در حال جستجوی آهنگ در یوتیوب...*\n\n🎵 {title} - {artist}", user_id=user_id)
                            from crawlers.youtube import search_youtube_track
                            vid_id = await search_youtube_track(title, artist, resolved.get("album", ""), "")
                            if vid_id:
                                await show_track_page(bot, chat_id, f"yt_{vid_id}", artwork_service, user_id, message_to_edit=status_msg)
                            else:
                                status_msg = await edit_message(status_msg, "❌ متأسفانه نسخه قابل دانلودی یافت نشد.", user_id=user_id)
                        else:
                            status_msg = await edit_message(status_msg, "❌ متأسفانه اطلاعات کافی برای این پیوند یافت نشد.", user_id=user_id)
            elif type_ == "direct_link":
                yt_m = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})', term)
                sc_m = re.search(r'soundcloud\.com\/([a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+)', term)

                if yt_m:
                    await show_track_page(bot, chat_id, f"yt_{yt_m.group(1)}", artwork_service, user_id)
                elif sc_m:
                    await show_track_page(bot, chat_id, f"sc_{sc_m.group(1)}", artwork_service, user_id)
                else:
                    await direct_download_service.ask_confirmation(chat_id, term, user_id=user_id)
            else:
                await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE)

@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    try:
        await handle_callback(bot, callback_query, api_client, user_settings_service,
                             artwork_service, search_cache_service, download_service,
                             rate_limiter, download_rate_limiter, direct_download_service)
    except Exception as e:
        if "query is too old" in str(e).lower():
            await bot.answer_callback_query(callback_query.id, "⚠️ این جستجو منقضی شده است. لطفاً مجدداً جستجو کنید.", show_alert=True)
        else:
            logger.error(f"Callback error: {e}")

def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("ABRAAVA bot is starting...")
    while True:
        try:
            bot.run()
        except KeyboardInterrupt: break
        except Exception as e:
            logger.exception(f"Bot crashed: {e}")
            time.sleep(60)
