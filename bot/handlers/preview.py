import asyncio
import io
from typing import Optional
from balethon import Client
from balethon.objects import Message
from core.logger import logger
from crawlers.utils import get_track
from crawlers.itunes import get_cached_preview, set_mirror
from utils.messages import send_message, edit_message, safe_delete
from core.http_client import HttpClient
from core.config import FOOTER
from bot.keyboards import create_close_button
from balethon.objects import InlineKeyboard, InlineKeyboardButton

async def _update_preview_status(bot, chat_id, msg, text):
    await safe_delete(msg)
    return await send_message(bot, chat_id, text, show_cancel=True)

async def send_voice_preview(bot: Client, chat_id: int, track_id: int, user_id: int = None, reply_to=None):
    status_msg = await send_message(bot, chat_id, "⏳ *در حال دریافت پیش‌نمایش...*", reply_to_message_id=reply_to)

    try:
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            status_msg = await _update_preview_status(bot, chat_id, status_msg, "اطلاعات آهنگ یافت نشد.")
            return status_msg

        track = track_data["results"][0]
        preview_url = track.get("previewUrl")
        if not preview_url:
            status_msg = await _update_preview_status(bot, chat_id, status_msg, "پیش‌نمایشی موجود نیست.")
            return status_msg

        caption = f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*\n\n{FOOTER}"

        from utils.helpers import generate_deep_link
        markup = []
        source_url = track.get("trackViewUrl") or track.get("previewUrl")
        if track_id:
            markup.append([InlineKeyboardButton(text="📋 کپی پیوند", copy_text=generate_deep_link("track", track_id))])
        if source_url:
            markup.append([InlineKeyboardButton(text="🌐 اطلاعات بیشتر", url=source_url)])
        markup.append([create_close_button(user_id)])

        reply_markup = InlineKeyboard(*markup)

        # Attempt 1: From Cache (mirror)
        preview_cache = await get_cached_preview(track_id)
        if preview_cache:
            try:
                await bot.send_voice(chat_id, voice=preview_cache, caption=caption, reply_markup=reply_markup)
                await safe_delete(status_msg)
                return status_msg
            except Exception as e:
                logger.error(f"Cache preview send failed: {e}")

        # Attempt 2: Direct URL or Manual Download/Upload
        session = await HttpClient.get_session()
        async with session.get(preview_url) as resp:
            if resp.status == 200:
                preview_data = io.BytesIO(await resp.read())
                preview_data.name = f"preview_{track_id}.mp3"
                msg = await bot.send_voice(chat_id, voice=preview_data, caption=caption, reply_markup=reply_markup)
                if msg and track_id:
                    await set_mirror('track', str(track_id), 'previewUrl', f'https://tapi.bale.ai/file/bot<token>/{msg.voice.id}')
                await safe_delete(status_msg)
            else:
                status_msg = await _update_preview_status(bot, chat_id, status_msg, "دریافت پیش‌نمایش با خطا مواجه شد.")
    except Exception as e:
        logger.error(f"Failed to send preview: {e}")
        status_msg = await _update_preview_status(bot, chat_id, status_msg, f"خطا: {str(e)[:50]}")

    return status_msg
