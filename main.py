from core.config import BOT_TOKEN, ADMIN_IDS
from balethon import Client
from balethon.objects import Message, CallbackQuery
from core.logger import logger
from core.config import API_BASE_URL, API_TOKEN, OFFLINE_MODE
from services.api_client import APIClient
from services.user_settings_service import UserSettingsService
from services.artwork_service import ArtworkService
from services.search_cache_service import search_cache_service
from services.message_owner_service import message_owner_service
from services.rate_limiter import RateLimiter, DownloadRateLimiter
from services.tracker import AlbumDownloadTracker
from services.tagging_service import TaggingService
from services.error_notifier import BaleUploadErrorNotifier
from services.download_service import DownloadService

from bot.handlers.commands import start_command, help_command, about_command
from bot.handlers.settings import settings_command, stats_command
from bot.handlers.search import handle_search, quick_search
from bot.handlers.callbacks import handle_callback
from bot.handlers.broadcast import process_broadcast_message
from utils.parser import parse_search_query
from utils.messages import send_message

import asyncio
import signal
import sys

# Initialize Services
api_client = APIClient(API_BASE_URL, API_TOKEN)
user_settings_service = UserSettingsService(api_client)
artwork_service = ArtworkService(api_client, user_settings_service)
rate_limiter = RateLimiter()
download_rate_limiter = DownloadRateLimiter()
album_tracker = AlbumDownloadTracker(api_client)
tagging_service = TaggingService()
error_notifier = BaleUploadErrorNotifier(api_client)

bot = Client(token=BOT_TOKEN)
download_service = DownloadService(bot, api_client, user_settings_service, artwork_service,
                                   tagging_service, error_notifier, album_tracker, download_rate_limiter)

@bot.on_initialize()
async def on_init():
    logger.info(f"Bot initialized. Offline Mode: {OFFLINE_MODE}")

@bot.on_message()
async def on_message(message: Message):
    if message.author.is_bot: return

    user_id = message.author.id
    chat_id = message.chat.id
    text = message.content or ""

    # Register user (simple version)
    await user_settings_service.get_settings(user_id)

    if text.startswith("/start"):
        await start_command(bot, message)
    elif text.startswith("/help"):
        await help_command(bot, message)
    elif text.startswith("/settings"):
        await settings_command(bot, message, user_settings_service)
    elif text.startswith("/stats"):
        await stats_command(bot, message, api_client, rate_limiter, download_rate_limiter)
    elif text.startswith("/about"):
        await about_command(bot, message)
    else:
        query = await parse_search_query(text)
        if query:
            type_, term = query
            settings = await user_settings_service.get_settings(user_id)
            if type_ == "quick" or settings.quick_mode:
                await quick_search(bot, chat_id, user_id, term, api_client, user_settings_service, download_service)
            else:
                await handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, OFFLINE_MODE)

@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    await handle_callback(bot, callback_query, api_client, user_settings_service,
                         artwork_service, search_cache_service, download_service,
                         rate_limiter, download_rate_limiter)

def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    bot.run()
