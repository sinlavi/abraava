import time, io, logging, asyncio
from typing import Optional, Union, Dict, Any, List
from core.logger import logger
from core.http_client import HttpClient
from crawlers.itunes import set_mirror, get_mirror
from crawlers.youtube import get_artist_image
from utils.helpers import get_high_res_artwork
from utils.image_utils import crop_to_square
from bot.keyboards import create_close_button
from core.config import PLATFORM

class ArtworkService:
    def __init__(self, api_client, user_settings_service):
        self.api_client, self.user_settings_service, self.auto_download_mode = api_client, user_settings_service, {}
    def _in_auto_download(self, user_id: int) -> bool: return time.time() < self.auto_download_mode.get(user_id, 0)
    async def get_cached_artwork_url(self, entity_type: str, entity_id: Union[int, str]) -> Optional[str]:
        mirrors = await get_mirror(entity_type, str(entity_id), 'artworkUrl')
        if mirrors and isinstance(mirrors, dict) and mirrors.get('artworkUrl'):
            cached_url = mirrors['artworkUrl'].get('url') if isinstance(mirrors['artworkUrl'], dict) else mirrors['artworkUrl']
            if cached_url and '<token>' in cached_url: return cached_url.split('<token>/')[-1]
            if cached_url and cached_url.startswith("tg://file/"): return cached_url.replace("tg://file/", "")
            return cached_url
        return None
    async def set_artwork_mirror(self, entity_type: str, entity_id: Union[int, str], file_id: str) -> bool:
        if not entity_id or not file_id: return False
        mirror_url = f"tg://file/{file_id}" if PLATFORM == "telegram" else f"https://tapi.bale.ai/file/bot<token>/{file_id}"
        return bool(await set_mirror(entity_type, str(entity_id), 'artworkUrl', mirror_url))
    async def get_artwork_for_display(self, entity_type: str, entity_id: int, artwork_url: Optional[str] = None, user_id: Optional[int] = None, entity_name: str = None) -> Optional[Union[str, bytes]]:
        if not (await self.user_settings_service.get_settings(user_id)).show_artwork: return None
        cached = await self.get_cached_artwork_url(entity_type, entity_id)
        if cached and not self._in_auto_download(user_id): return cached
        url = artwork_url or (get_artist_image(entity_name) if entity_type == "artist" and entity_name else None)
        if url:
            try:
                session = await HttpClient.get_session()
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return crop_to_square(data) if isinstance(entity_id, str) and entity_id.startswith(("yt_", "sc_")) else data
            except Exception as e: logger.error(f"Artwork download error: {e}")
        return None
    async def send_artwork_photo(self, bot, chat_id: int, artwork_data: Union[str, bytes], caption: str, reply_markup=None, entity_type: str = None, entity_id: int = None, user_id: int = None):
        try:
            from core.config import FOOTER
            await bot.send_chat_action(chat_id, "upload_photo")
            if isinstance(artwork_data, str): msg = await bot.send_photo(chat_id, photo=artwork_data, caption=f"{caption}{FOOTER}", reply_markup=reply_markup)
            else:
                photo_io = io.BytesIO(artwork_data); photo_io.name = "artwork.jpg"
                msg = await bot.send_photo(chat_id, photo=photo_io, caption=f"{caption}{FOOTER}", reply_markup=reply_markup)
                if msg and entity_type and entity_id:
                    photo = msg._msg.photo
                    await self.set_artwork_mirror(entity_type, entity_id, photo[0].id if PLATFORM == "bale" else photo[-1].file_id)
            return msg
        except Exception as e:
            logger.warning(f"Failed to send artwork: {e}")
            if user_id:
                self.auto_download_mode[user_id] = time.time() + 900
                from utils.messages import send_message
                await send_message(bot, chat_id, f"⚠️ *خطا در نمایش کاور*\nآیا مایلید مجدداً تلاش شود؟", reply_markup=[[{"text": "✅ بله، تلاش مجدد", "callback_data": f"force_artwork:{entity_type}:{entity_id}:{caption[:30]}:u{user_id}"}], [create_close_button(user_id)]])
            return None
    async def get_artwork_bytes(self, entity_id: Union[int, str], artwork_url100: str):
        url = get_high_res_artwork(artwork_url100, 600)
        if url:
            try:
                session = await HttpClient.get_session()
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return crop_to_square(data) if isinstance(entity_id, str) and entity_id.startswith(("yt_", "sc_")) else data
            except: pass
        return None
    async def force_manual_artwork(self, bot, chat_id: int, entity_type: str, entity_id: int, caption: str, user_id: int):
        try:
            from crawlers.itunes import lookup_itunes
            data = await lookup_itunes(entity_id, entity_type if entity_type != 'collection' else None)
            if not data or not data.get('results'): return
            item = data['results'][0]
            url = get_high_res_artwork(item.get('artworkUrl100') or item.get('artworkUrl')) or (get_artist_image(item.get('artistName')) if entity_type == "artist" else None)
            if not url: return
            session = await HttpClient.get_session()
            async with session.get(url, timeout=60) as resp:
                if resp.status == 200: await self.send_artwork_photo(bot, chat_id, await resp.read(), caption, entity_type=entity_type, entity_id=entity_id, user_id=user_id)
        except Exception as e: logger.error(f"Manual artwork error: {e}")
