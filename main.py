import os
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
from services.download_service import DownloadService
from services.direct_download_service import DirectDownloadService
from services.lyrics_service import LyricsService
from services.membership_service import verify_all_memberships
from services.message_owner_service import message_owner_service
from services.odesli_service import OdesliService

from bot.handlers.commands import start_command, help_command, settings_command, about_command, stats_command
from bot.handlers.search import handle_search, quick_search
from bot.handlers.details import show_artist_page, show_collection_page, show_track_page
from bot.handlers.callbacks import handle_callback
from utils.parser import parse_search_query
from utils.helpers import safe_delete
from utils.messages import send_message, edit_message

import asyncio
import re
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Bot instance
bot = Client(BOT_TOKEN)

@bot.on_message()
async def on_message(message: Message):
    if not message.text: return

    chat_id = message.chat.id
    user_id = message.author.id
    text = message.text
    is_group = message.chat.type in ["group", "supergroup"]

    # Initialize services
    async with HttpClient() as http_client:
        api_client = APIClient(http_client, API_BASE_URL, API_TOKEN)
        user_settings_service = UserSettingsService(api_client)
        artwork_service = ArtworkService(http_client)
        lyrics_service = LyricsService(http_client, api_client)
        download_service = DownloadService(http_client, api_client, lyrics_service)
        rate_limiter = RateLimiter(api_client)
        download_rate_limiter = DownloadRateLimiter(api_client)
        direct_download_service = DirectDownloadService(http_client, api_client, download_service)

        # Track handling
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
            await send_message(bot, chat_id, channels_text, reply_markup=InlineKeyboard(*markup_rows))
            return

    if text.startswith("/start"):
        # Deep link handling
        if len(text.split()) > 1:
            start_param = text.split()[1]
            if "_" in start_param:
                type_, item_id = start_param.split("_", 1)
                if item_id.isdigit(): item_id = int(item_id)
                if type_ == "artist": await show_artist_page(bot, chat_id, item_id, 1, artwork_service, user_id, reply_to=message.id)
                elif type_ == "collection": await show_collection_page(bot, chat_id, item_id, 1, artwork_service, user_id, reply_to=message.id)
                elif type_ == "track": await show_track_page(bot, chat_id, item_id, artwork_service, user_id, reply_to=message.id)
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
                await send_message(bot, chat_id, usage_map.get(type_, "⚠️ لطفا عبارت مورد نظر خود را وارد کنید."))
                return

            settings = await user_settings_service.get_settings(user_id)
            if type_ == "quick" or settings.quick_mode:
                await quick_search(bot, chat_id, user_id, term, api_client, user_settings_service, download_service, reply_to=message.id)
            elif type_ == "itunes_track":
                await show_track_page(bot, chat_id, int(term), artwork_service, user_id, reply_to=message.id)
            elif type_ == "itunes_album":
                await show_collection_page(bot, chat_id, int(term), 1, artwork_service, user_id, reply_to=message.id)
            elif type_ == "itunes_artist":
                await show_artist_page(bot, chat_id, int(term), 1, artwork_service, user_id, reply_to=message.id)
            elif type_ == "music_link":
                status_msg = await send_message(bot, chat_id, "🔍 *در حال بررسی پیوند...*", reply_to_message_id=message.id)
                resolved = await OdesliService.resolve_link(term)
                if not resolved:
                    status_msg = await edit_message(status_msg, "❌ متأسفانه اطلاعاتی برای این پیوند یافت نشد.")
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
                            status_msg = await edit_message(status_msg, f"🔍 *در حال جستجوی آهنگ در یوتیوب...*\n\n🎵 {title} - {artist}")
                            from crawlers.youtube import search_youtube_track
                            vid_id = await search_youtube_track(title, artist, resolved.get("album", ""), "")
                            if vid_id:
                                await show_track_page(bot, chat_id, f"yt_{vid_id}", artwork_service, user_id, message_to_edit=status_msg)
                            else:
                                status_msg = await edit_message(status_msg, "❌ متأسفانه نسخه قابل دانلودی یافت نشد.")
                        else:
                            status_msg = await edit_message(status_msg, "❌ متأسفانه اطلاعات کافی برای این پیوند یافت نشد.")
            elif type_ == "direct_link":
                yt_m = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})', term)
                sc_m = re.search(r'soundcloud\.com\/([a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+)', term)

                if yt_m:
                    await show_track_page(bot, chat_id, f"yt_{yt_m.group(1)}", artwork_service, user_id, reply_to=message.id)
                elif sc_m:
                    await show_track_page(bot, chat_id, f"sc_{sc_m.group(1)}", artwork_service, user_id, reply_to=message.id)
                else:
                    await direct_download_service.ask_confirmation(chat_id, term, user_id=user_id, reply_to=message.id)
            elif type_ in ["track", "album", "artist", "ytm", "sc", "quick"]:
                await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE, reply_to=message.id)
            else:
                if text.startswith("/"):
                    await send_message(bot, chat_id, "⚠️ *دستور وارد شده معتبر نیست.*\n\nبرای مشاهده راهنما از /help استفاده کنید.")
                else:
                    # Generic search fallback
                    await handle_search(bot, chat_id, user_id, "track", text, api_client, search_cache_service, OFFLINE_MODE, reply_to=message.id)

@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    try:
        await handle_callback(bot, callback_query, api_client, user_settings_service,
                             artwork_service, search_cache_service, download_service,
                             rate_limiter, download_rate_limiter, direct_download_service)
    except Exception as e:
        if "query is too old" in str(e).lower():
            await bot.answer_callback_query(callback_query.id, text="⚠️ این جستجو منقضی شده است. لطفاً مجدداً جستجو کنید.", show_alert=True)
        else:
            logger.error(f"Callback error: {e}")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return

def run_health_check_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health check server started on port {port}")
    server.serve_forever()

def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start health check server first to satisfy Render
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()

    # Start proxy setup in background
    from proxy_setup import setup_proxy
    threading.Thread(target=setup_proxy, daemon=True).start()

    logger.info("ABRAAVA bot is starting...")
    while True:
        try:
            bot.run()
        except KeyboardInterrupt: break
        except Exception as e:
            logger.exception(f"Bot crashed: {e}")
            time.sleep(60)
