from services.lyrics_service import lyrics_service
from crawlers.utils import get_track
from utils.messages import send_message, edit_message
from bot.keyboards import create_close_button
import logging, re

logger = logging.getLogger("ABRAAVA:LYRICS_HANDLER")

async def handle_lyrics_request(bot, chat_id, track_id, owner_id, message_to_edit=None, reply_to=None):
    status_msg = await edit_message(message_to_edit, "🔍 *در حال جستجوی متن آهنگ...*") if message_to_edit else await send_message(bot, chat_id, "🔍 *در حال جستجوی متن آهنگ...*", reply_to_message_id=reply_to)
    try:
        data = await get_track(track_id)
        if not data or not data.get("results"): await edit_message(status_msg, "❌ اطلاعات آهنگ یافت نشد."); return
        track = data["results"][0]
        lyrics_dict = await lyrics_service.get_lyrics(track_id, track.get("trackName"), track.get("artistName"))
        lyrics = lyrics_dict.get("plain") if lyrics_dict else None
        if not lyrics or lyrics == "Instrumental/Not exists": await edit_message(status_msg, "❌ متأسفانه متن این آهنگ یافت نشد."); return
        lyrics = re.sub(r'\n\s*\n\s*\n+', '\n\n', lyrics).strip()
        header, max_length, parts = f"📜 *متن آهنگ {track.get('trackName')} - {track.get('artistName')}*\n\n", 3800, []
        if len(header + lyrics) <= 4000: parts.append(header + lyrics)
        else:
            current_part, lines = header, lyrics.split("\n")
            for line in lines:
                if len(current_part + line + "\n") > max_length: parts.append(current_part.strip()); current_part = ""
                current_part += line + "\n"
            if current_part: parts.append(current_part.strip())
        for i, part in enumerate(parts):
            markup = [[create_close_button(owner_id)]] if i == len(parts) - 1 else None
            if i == 0: status_msg = await edit_message(status_msg, part, reply_markup=markup)
            else: await send_message(bot, chat_id, part, reply_markup=markup)
    except Exception as e: logger.error(f"Error handling lyrics request: {e}"); await edit_message(status_msg, f"❌ خطا در دریافت متن آهنگ: {e}")
