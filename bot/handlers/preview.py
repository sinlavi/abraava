from core.platform import InlineKeyboardButton, InlineKeyboard, MessageAdapter
from utils.messages import send_message, edit_message, safe_delete
from bot.keyboards import create_close_button
import logging

logger = logging.getLogger("ABRAAVA:PREVIEW")

async def send_voice_preview(bot, chat_id, track_id, user_id):
    from crawlers.utils import get_track
    track_data = await get_track(track_id)
    if not track_data or not track_data.get("results"):
        return

    track = track_data["results"][0]
    preview_url = track.get("previewUrl")
    if not preview_url:
        return

    status_msg = await send_message(bot, chat_id, "⏳ *در حال دریافت پیش‌نمایش...*")

    try:
        from core.http_client import HttpClient
        session = await HttpClient.get_session()
        async with session.get(preview_url) as resp:
            if resp.status == 200:
                audio_bytes = await resp.read()
                import io
                voice_io = io.BytesIO(audio_bytes)
                voice_io.name = "preview.m4a"

                track_name = track.get("trackName", "نامشخص")
                artist_name = track.get("artistName", "نامشخص")
                caption = f"🎧 *پیش‌نمایش آهنگ:*\n\n🎵 {track_name}\n🎤 {artist_name}"

                markup = [[create_close_button(user_id)]]
                await bot.send_voice(chat_id, voice=voice_io, caption=caption, reply_markup=InlineKeyboard(*markup))
                await safe_delete(status_msg)
            else:
                await edit_message(status_msg, "❌ خطا در دریافت پیش‌نمایش.")
    except Exception as e:
        logger.error(f"Error sending preview: {e}")
        await edit_message(status_msg, "❌ خطا در ارسال پیش‌نمایش.")
