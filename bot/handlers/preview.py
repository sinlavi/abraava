import asyncio
import io
from typing import Optional
from balethon import Client
from balethon.objects import Message
from core.logger import logger
from crawlers.utils import get_track
from crawlers.itunes import get_cached_preview, set_mirror
from utils.messages import send_message

async def send_voice_preview(bot: Client, chat_id: int, track_id: int, user_id: int = None):
    status_msg = await send_message(bot, chat_id, "⏳ *در حال دریافت پیش‌نمایش...*")
    try:
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            await status_msg.edit("اطلاعات آهنگ یافت نشد.")
            return

        track = track_data["results"][0]
        preview_url = track.get("previewUrl")
        if not preview_url:
            await status_msg.edit("پیش‌نمایشی موجود نیست.")
            return

        preview_cache = await get_cached_preview(track_id)
        if preview_cache:
            try:
                await bot.send_voice(chat_id, voice=preview_cache, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*")
                await status_msg.delete()
                return
            except Exception as e:
                logger.error(f"Cache preview send failed: {e}")

        session = await HttpClient.get_session() if 'HttpClient' in globals() else None
        if not session:
             from core.http_client import HttpClient
             session = await HttpClient.get_session()

        async with session.get(preview_url) as resp:
            if resp.status == 200:
                preview_data = io.BytesIO(await resp.read())
                preview_data.name = f"preview_{track_id}.mp3"
                msg = await bot.send_voice(chat_id, voice=preview_data, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*")
                if msg and track_id:
                    await set_mirror('track', str(track_id), 'previewUrl', f'https://tapi.bale.ai/file/bot<token>/{msg.voice.id}')
                await status_msg.delete()
            else:
                await status_msg.edit("دریافت پیش‌نمایش با خطا مواجه شد.")
    except Exception as e:
        logger.error(f"Failed to send preview: {e}")
        await status_msg.edit(f"خطا: {str(e)[:50]}")
