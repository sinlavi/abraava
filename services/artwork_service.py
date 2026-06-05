import time
import io
import logging
from typing import Optional, Union, Dict, Any
from balethon import Client
from balethon.objects import Message, InlineKeyboard, InlineKeyboardButton
from core.logger import logger
from core.http_client import HttpClient
from services.api_client import APIClient
from crawlers.itunes import set_mirror, get_mirror
from utils.helpers import get_high_res_artwork
from utils.messages import send_message, edit_message

class ArtworkService:
    def __init__(self, api_client: APIClient, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service

    async def get_cached_artwork_url(self, entity_type: str, entity_id: int) -> Optional[str]:
        try:
            if not entity_id:
                return None
            data = await get_mirror(entity_type, str(entity_id), 'artworkUrl')
            if data and isinstance(data, dict):
                # Logic from main.py for extracting file_id or url
                artwork_data = data.get('mirrors', {}).get('artworkUrl')
                if not artwork_data and 'data' in data:
                    artwork_data = data['data'].get('mirrors', {}).get('artworkUrl')

                if artwork_data:
                    cached_url = artwork_data.get('url') if isinstance(artwork_data, dict) else artwork_data
                    if cached_url:
                        if '<token>' in cached_url:
                            return cached_url.split('<token>/')[-1]
                        return cached_url
            return None
        except Exception as e:
            logger.error(f"Error getting cached artwork for {entity_type}:{entity_id}: {e}")
            return None

    async def set_artwork_mirror(self, entity_type: str, entity_id: int, file_id: str) -> bool:
        try:
            if not entity_id or not file_id:
                return False
            artwork_url = f'https://tapi.bale.ai/file/bot<token>/{file_id}'
            result = await set_mirror(entity_type, str(entity_id), 'artworkUrl', artwork_url)
            return bool(result)
        except Exception as e:
            logger.error(f"Error setting artwork mirror for {entity_type}:{entity_id}: {e}")
            return False

    async def get_artwork_for_display(self, entity_type: str, entity_id: int,
                                       artwork_url: Optional[str] = None,
                                       user_id: Optional[int] = None) -> Optional[Union[str, bytes]]:
        settings = await self.user_settings_service.get_settings(user_id)
        if not settings.show_artwork:
            return None

        cached_file_id = await self.get_cached_artwork_url(entity_type, entity_id)
        if cached_file_id:
            return cached_file_id

        if artwork_url:
            try:
                session = await HttpClient.get_session()
                async with session.get(artwork_url, timeout=30) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception as e:
                logger.error(f"Error downloading artwork for {entity_type}:{entity_id}: {e}")
        return None

    async def send_artwork_photo(self, bot: Client, chat_id: int, artwork_data: Union[str, bytes],
                                  caption: str, reply_markup=None,
                                  entity_type: str = None, entity_id: int = None):
        try:
            if isinstance(artwork_data, str):
                msg = await bot.send_photo(chat_id, photo=artwork_data, caption=caption, reply_markup=reply_markup)
            else:
                photo_io = io.BytesIO(artwork_data)
                photo_io.name = "artwork.jpg"
                msg = await bot.send_photo(chat_id, photo=photo_io, caption=caption, reply_markup=reply_markup)

                if msg and msg.photo and entity_type and entity_id:
                    file_id = str(msg.photo[0].id)
                    await self.set_artwork_mirror(entity_type, entity_id, file_id)
            return msg
        except Exception as e:
            logger.error(f"Failed to send artwork photo: {e}")
            raise
