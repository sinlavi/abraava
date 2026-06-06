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
from core.config import PROXY, FOOTER

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

    def _get_proxy(self):
        """Return SOCKS5 proxy URL from config or check for local WARP/Dante."""
        if PROXY: return PROXY

        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", 1080)) == 0:
                return "socks5://127.0.0.1:1080"
        except: pass
        finally: s.close()
        return None

    def _build_opts(self, url, output_dir=None, quality="192", method=1):
        opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_check_certificate': True,
            'http_headers': self._get_random_headers(),
            'retries': 5
        }

        if output_dir:
            opts['outtmpl'] = f'{output_dir}/%(title)s.%(ext)s'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': quality,
            }]
        else:
            opts['skip_download'] = True

        proxy = self._get_proxy()

        # Method 1: Default with random headers
        # Method 2: With Proxy
        # Method 3: With specific extractor args for YouTube
        if method == 2 and proxy:
            opts['proxy'] = proxy
        elif method == 3:
            if "youtube.com" in url or "youtu.be" in url:
                opts['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
            if proxy: opts['proxy'] = proxy

        return opts

    async def get_metadata(self, url):
        # Try different methods to get metadata
        for method in [1, 2, 3]:
            opts = self._build_opts(url, method=method)
            try:
                loop = asyncio.get_event_loop()
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    return {
                        'title': info.get('title', 'Unknown'),
                        'uploader': info.get('uploader', info.get('artist', 'Unknown')),
                        'album': info.get('album', ''),
                        'url': url,
                        'upload_date': info.get('upload_date', '')
                    }
            except Exception as e:
                logger.debug(f"Metadata fetch failed with method {method}: {e}")
                continue
        return None

    async def ask_confirmation(self, chat_id, url):
        status_msg = await send_message(self.bot, chat_id, "⏳ *در حال دریافت اطلاعات از پیوند...*")
        meta = await self.get_metadata(url)
        if not meta:
            await edit_message(status_msg, "❌ خطا در دریافت اطلاعات پیوند. ممکن است پیوند نامعتبر باشد یا دسترسی به آن مسدود شده باشد.")
            return

        text = f"🎵 *اطلاعات یافت شده:*\n\n"
        text += f"🔹 نام: {meta['title']}\n"
        text += f"🔹 هنرمند: {meta['uploader']}\n"
        if meta['album']: text += f"🔹 آلبوم: {meta['album']}\n"
        text += f"\nآیا مایل به دانلود این ترک هستید؟"

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

        success = False
        track_data = {}
        mp3_path = None

        try:
            # Try different methods for download
            for method in [1, 2, 3]:
                opts = self._build_opts(url, output_dir=temp_dir, quality=quality, method=method)
                try:
                    loop = asyncio.get_event_loop()
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

                        track_data = {
                            'trackName': info.get('title', 'Unknown'),
                            'artistName': info.get('uploader', info.get('artist', 'Unknown')),
                            'collectionName': info.get('album', ''),
                            'releaseDate': info.get('upload_date', '')[:4],
                        }

                        files = list(Path(temp_dir).glob("*.mp3"))
                        if files:
                            mp3_path = files[0]
                            success = True
                            break
                except Exception as e:
                    logger.warning(f"Download method {method} failed: {e}")
                    continue

            if success and mp3_path:
                await edit_message(status_msg, "☁️ *در حال آماده‌سازی فایل...*")
                self.tagging_service.tag_mp3(mp3_path, track_data)

                caption = f"🎵 *نام آهنگ:* {track_data['trackName']}\n"
                caption += f"🎤 *نام هنرمند:* {track_data['artistName']}\n"
                if track_data['collectionName']: caption += f"💿 *نام آلبوم:* {track_data['collectionName']}\n"
                caption += f"📀 *کیفیت دانلود:* {quality} kbps"

                with open(mp3_path, 'rb') as f:
                    await self.bot.send_audio(chat_id, audio=f, caption=f"{caption}{FOOTER}", reply_markup=InlineKeyboard([[create_close_button()]]))
                await status_msg.delete()
            else:
                await edit_message(status_msg, "❌ دانلود با خطا مواجه شد. تمامی روش‌ها ناموفق بودند.")

        except Exception as e:
            logger.error(f"Direct download service error: {e}")
            await edit_message(status_msg, f"❌ خطا: {str(e)[:50]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
