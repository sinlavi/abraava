import time
import io
import logging
import asyncio
from typing import Optional, Union, Dict, Any, List
from balethon import Client
from balethon.objects import Message, InlineKeyboard, InlineKeyboardButton
from core.logger import logger
from core.http_client import HttpClient
from services.api_client import APIClient
from crawlers.itunes import set_mirror, get_mirror
from crawlers.youtube import get_artist_image
from utils.helpers import get_high_res_artwork
from bot.keyboards import create_close_button

class ArtworkService:
    def __init__(self, api_client: APIClient, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service
        self.auto_download_mode = {} # user_id -> end_timestamp

    def _in_auto_download(self, user_id: int) -> bool:
        ts = self.auto_download_mode.get(user_id, 0)
        return time.time() < ts

    async def get_cached_artwork_url(self, entity_type: str, entity_id: int) -> Optional[str]:
        try:
            if not entity_id: return None
            # Skip mirroring for external sources
            if isinstance(entity_id, str) and entity_id.startswith(("yt_", "sc_", "sp_")):
                return None

            data = await get_mirror(entity_type, str(entity_id), 'artworkUrl')
            if data and isinstance(data, dict):
                artwork_data = data.get('mirrors', {}).get('artworkUrl')
                if not artwork_data and 'data' in data:
                    artwork_data = data['data'].get('mirrors', {}).get('artworkUrl')

                if artwork_data:
                    cached_url = artwork_data.get('url') if isinstance(artwork_data, dict) else artwork_data
                    if cached_url and '<token>' in cached_url:
                        return cached_url.split('<token>/')[-1]
                    return cached_url
            return None
        except Exception as e:
            logger.error(f"Error getting cached artwork: {e}")
            return None

    async def set_artwork_mirror(self, entity_type: str, entity_id: Union[int, str], file_id: str) -> bool:
        try:
            if not entity_id or not file_id: return False
            # Skip mirroring for external sources
            if isinstance(entity_id, str) and entity_id.startswith(("yt_", "sc_", "sp_")):
                return False

            artwork_url = f'https://tapi.bale.ai/file/bot<token>/{file_id}'
            result = await set_mirror(entity_type, str(entity_id), 'artworkUrl', artwork_url)
            return bool(result)
        except Exception as e:
            logger.error(f"Error setting artwork mirror: {e}")
            return False

    async def get_artwork_for_display(self, entity_type: str, entity_id: int,
                                       artwork_url: Optional[str] = None,
                                       user_id: Optional[int] = None,
                                       entity_name: str = None) -> Optional[Union[str, bytes]]:
        logger.info(f"Retrieving artwork for {entity_type} {entity_id} ({entity_name}) for user {user_id}")
        settings = await self.user_settings_service.get_settings(user_id)
        if not settings.show_artwork:
            logger.info(f"Artwork display is disabled for user {user_id}")
            return None

        cached_file_id = await self.get_cached_artwork_url(entity_type, entity_id)
        if cached_file_id and not self._in_auto_download(user_id):
            logger.info(f"Using cached artwork file_id: {cached_file_id}")
            return cached_file_id

        # Fallback for artist artwork from YouTube Music
        final_url = artwork_url
        if entity_type == "artist" and not final_url and entity_name:
            final_url = get_artist_image(entity_name)

        if final_url:
            try:
                session = await HttpClient.get_session()
                async with session.get(final_url, timeout=30) as resp:
                    if resp.status == 200: return await resp.read()
            except Exception as e:
                logger.error(f"Error downloading artwork: {e}")
        return None

    async def send_artwork_photo(self, bot: Client, chat_id: int, artwork_data: Union[str, bytes],
                                  caption: str, reply_markup=None,
                                  entity_type: str = None, entity_id: int = None,
                                  user_id: int = None):
        try:
            from utils.messages import _prepare_markup, FOOTER, send_message
            markup = _prepare_markup(reply_markup, False)

            try:
                if isinstance(artwork_data, str):
                    msg = await bot.send_photo(chat_id, photo=artwork_data, caption=f"{caption}{FOOTER}", reply_markup=markup)
                else:
                    photo_io = io.BytesIO(artwork_data)
                    photo_io.name = "artwork.jpg"
                    msg = await bot.send_photo(chat_id, photo=photo_io, caption=f"{caption}{FOOTER}", reply_markup=markup)

                    if msg and msg.photo and entity_type and entity_id:
                        file_id = str(msg.photo[0].id)
                        await self.set_artwork_mirror(entity_type, entity_id, file_id)
                return msg
            except Exception as e:
                logger.warning(f"Failed to send artwork: {e}")
                # Ask user if they want to force download/upload or skip
                if user_id:
                    self.auto_download_mode[user_id] = time.time() + 900 # 15 mins
                    text = f"⚠️ *خطا در نمایش کاور*\nآیا مایلید مجدداً تلاش شود؟ (در صورت تایید کاور مستقیماً دانلود و آپلود می‌شود)"
                    retry_markup = [
                        [InlineKeyboardButton(text="✅ بله، تلاش مجدد", callback_data=f"force_artwork:{entity_type}:{entity_id}:{caption[:30]}")],
                        [InlineKeyboardButton(text="❌ خیر، بدون کاور بفرست", callback_data="close")]
                    ]
                    await send_message(bot, chat_id, text, reply_markup=retry_markup)
                return None
        except Exception as e:
            logger.error(f"Failed in send_artwork_photo helper: {e}")
            raise

    async def get_artwork_bytes(self, entity_id: int, artwork_url100: str):
        if entity_id:
            url = get_high_res_artwork(artwork_url100, 600)
            if url:
                session = await HttpClient.get_session()
                try:
                    async with session.get(url, timeout=30) as resp:
                        if resp.status == 200: return await resp.read()
                except: pass
        return None

    async def force_manual_artwork(self, bot: Client, chat_id: int, entity_type: str, entity_id: int, caption: str, user_id: int):
        """Attempts to recovery artwork by direct download and upload when mirrors fail."""
        try:
            # 1. Get metadata to find the official URL if not provided
            # For simplicity, we assume we need to find it again or it was passed
            # Let's try to get it from itunes lookup
            from crawlers.itunes import lookup_itunes
            data = await lookup_itunes(entity_id, entity_type if entity_type != 'collection' else None)
            if not data or not data.get('results'):
                await bot.send_message(chat_id, "❌ خطا در یافتن اطلاعات برای بازیابی کاور.")
                return

            item = data['results'][0]
            artwork_url = get_high_res_artwork(item.get('artworkUrl100') or item.get('artworkUrl'))

            if not artwork_url and entity_type == "artist":
                artwork_url = get_artist_image(item.get('artistName'))

            if not artwork_url:
                await bot.send_message(chat_id, "❌ کاوری یافت نشد.")
                return

            # 2. Download bytes
            session = await HttpClient.get_session()
            async with session.get(artwork_url, timeout=60) as resp:
                if resp.status != 200:
                    await bot.send_message(chat_id, "❌ خطا در دانلود مستقیم کاور.")
                    return
                artwork_bytes = await resp.read()

            # 3. Send and Mirror
            await self.send_artwork_photo(bot, chat_id, artwork_bytes, caption, entity_type=entity_type, entity_id=entity_id, user_id=user_id)

        except Exception as e:
            logger.error(f"Error in force_manual_artwork: {e}")
            await bot.send_message(chat_id, f"❌ خطای غیرمنتظره در بازیابی کاور: {e}")
