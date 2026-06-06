import asyncio
import os
import shutil
import uuid
import yt_dlp
from pathlib import Path
from core.logger import logger
from utils.messages import send_message, edit_message
from bot.keyboards import create_close_button
from balethon.objects import InlineKeyboardButton, InlineKeyboard

class DirectDownloadService:
    def __init__(self, bot, tagging_service):
        self.bot = bot
        self.tagging_service = tagging_service

    async def get_metadata(self, url):
        ydl_opts = {'quiet': True, 'skip_download': True}
        try:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                return {
                    'title': info.get('title', 'Unknown'),
                    'uploader': info.get('uploader', info.get('artist', 'Unknown')),
                    'album': info.get('album', ''),
                    'url': url
                }
        except Exception as e:
            logger.error(f"Metadata fetch failed: {e}")
            return None

    async def ask_confirmation(self, chat_id, url):
        status_msg = await send_message(self.bot, chat_id, "⏳ *در حال دریافت اطلاعات از پیوند...*")
        meta = await self.get_metadata(url)
        if not meta:
            await edit_message(status_msg, "❌ خطا در دریافت اطلاعات پیوند.")
            return

        text = f"🎵 *اطلاعات یافت شده:*\n\n"
        text += f"🔹 نام: {meta['title']}\n"
        text += f"🔹 هنرمند: {meta['uploader']}\n"
        if meta['album']: text += f"🔹 آلبوم: {meta['album']}\n"
        text += f"\nآیا مایل به دانلود این ترک هستید؟"

        # Using hex for URL safety in callback
        url_hash = uuid.uuid4().hex[:8]
        # We need a way to store this mapping temporarily
        # For now, let's pass the URL if it's short, or use a simple cache
        # To keep it stateless, let's base64 it or just pass it if allowed
        # Actually, Balethon callback_data limit is quite small.
        # Let's use a simpler confirmation without the URL in callback,
        # or use the fact that the message text has the info.

        from bot.handlers.callbacks import store_direct_link
        link_id = await store_direct_link(url)

        markup = [
            [InlineKeyboardButton(text="✅ بله، دانلود کن", callback_data=f"confirm_dl:{link_id}")],
            [InlineKeyboardButton(text="❌ خیر، انصراف", callback_data="close")]
        ]
        await edit_message(status_msg, text, reply_markup=markup)

    async def download_direct(self, chat_id, url, user_id, quality="192"):
        status_msg = await send_message(self.bot, chat_id, f"⏳ *در حال شروع دانلود...*")

        unique_id = uuid.uuid4().hex
        temp_dir = os.path.join(os.getcwd(), "downloads", unique_id)
        os.makedirs(temp_dir, exist_ok=True)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{temp_dir}/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': quality,
            }],
            'quiet': True,
        }

        try:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

                await edit_message(status_msg, "☁️ *در حال آماده‌سازی فایل...*")

                track_data = {
                    'trackName': info.get('title', 'Unknown'),
                    'artistName': info.get('uploader', info.get('artist', 'Unknown')),
                    'collectionName': info.get('album', ''),
                    'releaseDate': info.get('upload_date', '')[:4],
                }

                files = list(Path(temp_dir).glob("*.mp3"))
                if not files: raise Exception("File not found")

                mp3_path = files[0]
                self.tagging_service.tag_mp3(mp3_path, track_data)

                caption = f"🎵 *نام آهنگ:* {track_data['trackName']}\n"
                caption += f"🎤 *نام هنرمند:* {track_data['artistName']}\n"
                if track_data['collectionName']: caption += f"💿 *نام آلبوم:* {track_data['collectionName']}\n"
                caption += f"📀 *کیفیت دانلود:* {quality} kbps"

                from core.config import FOOTER
                with open(mp3_path, 'rb') as f:
                    await self.bot.send_audio(chat_id, audio=f, caption=f"{caption}{FOOTER}", reply_markup=InlineKeyboard([create_close_button()]))

                await status_msg.delete()

        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            await edit_message(status_msg, f"❌ خطا در دانلود: {str(e)[:50]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
