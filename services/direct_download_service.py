import asyncio
import os
import shutil
import uuid
import yt_dlp
from pathlib import Path
from core.logger import logger
from utils.messages import send_message, edit_message

class DirectDownloadService:
    def __init__(self, bot, tagging_service):
        self.bot = bot
        self.tagging_service = tagging_service

    async def download_direct(self, chat_id, url, user_id, quality="192"):
        status_msg = await send_message(self.bot, chat_id, "⏳ *در حال دریافت اطلاعات از پیوند...*")

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

                # Best effort mapping of yt_dlp info to track data for tagging
                track_data = {
                    'trackName': info.get('title', 'Unknown'),
                    'artistName': info.get('uploader', info.get('artist', 'Unknown')),
                    'collectionName': info.get('album', ''),
                    'releaseDate': info.get('upload_date', '')[:4],
                }

                # Check for mp3 file
                files = list(Path(temp_dir).glob("*.mp3"))
                if not files: raise Exception("File not found after download")

                mp3_path = files[0]
                self.tagging_service.tag_mp3(mp3_path, track_data)

                caption = f"🎵 *نام آهنگ:* {track_data['trackName']}\n"
                caption += f"🎤 *نام هنرمند:* {track_data['artistName']}\n"
                if track_data['collectionName']: caption += f"💿 *نام آلبوم:* {track_data['collectionName']}\n"
                caption += f"📀 *کیفیت دانلود:* {quality} kbps"

                with open(mp3_path, 'rb') as f:
                    await self.bot.send_audio(chat_id, audio=f, caption=caption)

                await status_msg.delete()

        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            await edit_message(status_msg, f"❌ خطا در دانلود مستقیم: {str(e)[:50]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
