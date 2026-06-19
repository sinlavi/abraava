import io
from bot.keyboards import create_close_button
from core.http_client import HttpClient
from core.config import FOOTER
from crawlers.itunes import get_cached_preview, set_mirror
from crawlers.utils import get_track
from utils.messages import send_message, safe_delete
from core.logger import logger

async def send_voice_preview(bot, chat_id, track_id, user_id=None, reply_to=None):
    status_msg = await send_message(bot, chat_id, "⏳ *در حال دریافت پیش‌نمایش...*", reply_to_message_id=reply_to)
    try:
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            await safe_delete(status_msg); await send_message(bot, chat_id, "اطلاعات آهنگ یافت نشد.", show_cancel=True); return
        track = track_data["results"][0]
        preview_url = track.get("previewUrl")
        if not preview_url:
            await safe_delete(status_msg); await send_message(bot, chat_id, "پیش‌نمایشی موجود نیست.", show_cancel=True); return
        from utils.helpers import generate_deep_link
        markup = [[{"text": "📋 کپی پیوند", "copy_text": generate_deep_link("track", track_id)}], [{"text": "🌐 اطلاعات بیشتر", "url": track.get("trackViewUrl") or preview_url}], [create_close_button(user_id)]]
        preview_cache = await get_cached_preview(track_id)
        if preview_cache:
            try:
                await bot.send_voice(chat_id, voice=preview_cache, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*\n\n{FOOTER}", reply_markup=markup)
                await safe_delete(status_msg); return
            except Exception as e: logger.error(f"Cache preview send failed: {e}")
        session = await HttpClient.get_session()
        async with session.get(preview_url) as resp:
            if resp.status == 200:
                preview_data = io.BytesIO(await resp.read()); preview_data.name = f"preview_{track_id}.mp3"
                msg = await bot.send_voice(chat_id, voice=preview_data, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*\n\n{FOOTER}", reply_markup=markup)
                await safe_delete(status_msg)
            else: await safe_delete(status_msg); await send_message(bot, chat_id, "دریافت پیش‌نمایش با خطا مواجه شد.", show_cancel=True)
    except Exception as e: logger.error(f"Failed to send preview: {e}"); await safe_delete(status_msg); await send_message(bot, chat_id, f"خطا: {str(e)[:50]}", show_cancel=True)
