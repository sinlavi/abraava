import asyncio
import os
import shutil
import uuid
import yt_dlp
import random
from pathlib import Path
from core.logger import logger
from utils.messages import send_message, edit_message
from bot.keyboards import create_close_button
from balethon.objects import InlineKeyboardButton, InlineKeyboard

# ── User‑agent list (Same as youtube crawler) ────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
]

class DirectDownloadService:
    def __init__(self, bot, tagging_service):
        self.bot = bot
        self.tagging_service = tagging_service

    def _get_random_headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        }

    async def get_metadata(self, url):
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'http_headers': self._get_random_headers(),
            'no_check_certificate': True
        }
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
            'http_headers': self._get_random_headers(),
            'no_check_certificate': True,
            'retries': 10
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
                    await self.bot.send_audio(chat_id, audio=f, caption=f"{caption}{FOOTER}", reply_markup=InlineKeyboard([[create_close_button()]]))

                await status_msg.delete()

        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            await edit_message(status_msg, f"❌ خطا در دانلود: {str(e)[:50]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
