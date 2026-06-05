import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional, Union, List
from balethon import Client
from balethon.objects import Message, InlineKeyboardButton, InlineKeyboard
from core.logger import logger
from core.config import OFFLINE_MODE, DEFAULT_QUALITY
from core.http_client import HttpClient
from models.schemas import DownloadQuality
from crawlers.utils import get_track, get_or_crawl_collection, get_or_crawl_collection_tracks
from crawlers.youtube import search_youtube_track, download_audio
from crawlers.itunes import get_cached_audio, set_mirror, get_cached_artwork, get_mirror
from utils.helpers import get_high_res_artwork
from utils.messages import send_message, edit_message

class DownloadService:
    def __init__(self, bot, api_client, user_settings_service, artwork_service,
                 tagging_service, error_notifier, album_tracker, download_rate_limiter):
        self.bot = bot
        self.api_client = api_client
        self.user_settings_service = user_settings_service
        self.artwork_service = artwork_service
        self.tagging_service = tagging_service
        self.error_notifier = error_notifier
        self.album_tracker = album_tracker
        self.download_rate_limiter = download_rate_limiter
        self.download_semaphore = asyncio.Semaphore(20)

    async def download_and_send_track(self, chat_id, track_id, user_id, status_msg=None,
                                     is_batch=False, album_cover_bytes=None, collection_id=None,
                                     selected_quality=None):

        if status_msg is None and not is_batch:
            status_msg = await send_message(self.bot, chat_id, "⏳ *در حال آماده‌سازی دانلود...*")

        track_data = await get_track(track_id, status_msg)
        if not track_data or not track_data.get("results"):
            await edit_message(status_msg, "خطا در دریافت اطلاعات آهنگ.")
            return

        track = track_data["results"][0]
        settings = await self.user_settings_service.get_settings(user_id)

        quality_value = selected_quality or settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        caption = self._build_caption(track, quality_value)

        # Check cache
        audio_cache = await get_cached_audio(track_id, quality=quality_value)
        if audio_cache:
            try:
                await edit_message(status_msg, "📤 *در حال ارسال فایل از حافظه کش...*")
                markup = self._build_audio_markup(track_id)
                await self.bot.send_audio(chat_id, audio=audio_cache, caption=caption, reply_markup=InlineKeyboard(*markup))
                await status_msg.delete()
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''),
                                                 track.get('artistName', ''), track.get('collectionName', ''),
                                                 0, 'cache', quality_value)
                # Clear error notification if it was active and we succeeded
                await self.error_notifier.check_and_clear_if_resolved(self.bot, test_success=True)
                return
            except Exception as e:
                logger.error(f"Cache send failed: {e}")
                if collection_id:
                    async def cancel_album(): self.album_tracker.cancel_download(user_id, collection_id)
                    await self.error_notifier.notify_upload_error(self.bot, str(e), cancel_album)

        if OFFLINE_MODE:
            await edit_message(status_msg, "بات در حالت آفلاین است.")
            return

        # Download from YouTube
        cover_bytes = album_cover_bytes
        if settings.show_artwork and cover_bytes is None:
            cover_bytes = await self.artwork_service.get_artwork_bytes(track.get('collectionId'), track.get('artworkUrl100'))

        await edit_message(status_msg, "🔍 *در حال جستجوی منبع با کیفیت...*")
        video_id = await search_youtube_track(track.get("trackName", ""), track.get("artistName", ""),
                                            track.get("collectionName", ""), track.get("releaseDate", "")[:4])

        if not video_id:
            await edit_message(status_msg, "لینک مناسبی یافت نشد.")
            return

        video_url = f"https://music.youtube.com/watch?v={video_id}"
        temp_dir = None
        try:
            async with self.download_semaphore:
                if collection_id:
                    self.album_tracker.start_track(user_id, collection_id, track.get("trackName", ""))

                await edit_message(status_msg, f"⏳ *در حال دانلود با کیفیت {quality_value}kbps...*")
                mp3_path = await download_audio(video_url, quality=quality_value)
                if not mp3_path: raise Exception("Download failed")

                temp_dir = os.path.dirname(mp3_path)
                self.tagging_service.tag_mp3(Path(mp3_path), track, cover_bytes)

                await edit_message(status_msg, "☁️ *در حال آپلود روی سرورهای ابری...*")

                markup = self._build_audio_markup(track_id)
                with open(mp3_path, 'rb') as f:
                    msg = await self.bot.send_audio(chat_id, audio=f, caption=caption, reply_markup=InlineKeyboard(*markup))
                    if msg and track_id:
                        await set_mirror('track', str(track_id), 'audioUrl',
                                         f'https://tapi.bale.ai/file/bot<token>/{msg.audio.id}',
                                         quality=quality_value)

                file_size = os.path.getsize(mp3_path)
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''),
                                                 track.get('artistName', ''), track.get('collectionName', ''),
                                                 file_size, 'youtube', quality_value)
                self.download_rate_limiter.record_download(user_id, quality_value)
                await self.error_notifier.check_and_clear_if_resolved(self.bot, test_success=True)
                await status_msg.delete()
        except Exception as e:
            logger.error(f"Download error: {e}")
            await edit_message(status_msg, "خطا در دانلود.")
            # Trigger error notification
            cancel_cb = None
            if collection_id:
                async def cancel_album(): self.album_tracker.cancel_download(user_id, collection_id)
                cancel_cb = cancel_album
            await self.error_notifier.notify_upload_error(self.bot, str(e), cancel_cb)
        finally:
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_caption(self, track, quality_value):
        parts = [
            f"🎵 *نام آهنگ:* {track.get('trackName', 'Unknown')}",
            f"🎤 *نام هنرمند:* {track.get('artistName', 'Unknown')}",
        ]
        if track.get('collectionName'):
            parts.append(f"💿 *نام آلبوم:* {track.get('collectionName')}")
        parts.append(f"📀 *کیفیت دانلود:* {quality_value} kbps")
        return "\n".join(parts)

    def _build_audio_markup(self, track_id):
        return [
            [InlineKeyboardButton(text="📂 نمایش در مینی اپ", web_app=f"https://player.abraava.ir?id={track_id}")],
            [InlineKeyboardButton(text="📋 کپی پیوند", copy_text=f"https://player.abraava.ir?id={track_id}")],
            [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
        ]
