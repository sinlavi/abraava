import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional, Union, List
from balethon import Client
from balethon.objects import Message, InlineKeyboardButton, InlineKeyboard
from core.logger import logger
from core.config import OFFLINE_MODE, DEFAULT_QUALITY, FOOTER
from core.http_client import HttpClient
from models.schemas import DownloadQuality
from crawlers.utils import get_track, get_or_crawl_collection, get_or_crawl_collection_tracks
from crawlers.youtube import search_youtube_track, download_audio
from crawlers.itunes import get_cached_audio, set_mirror, get_cached_artwork, get_mirror
from utils.helpers import get_high_res_artwork, format_duration, generate_deep_link
from utils.messages import send_message, edit_message, safe_delete
from bot.keyboards import create_close_button

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

    async def _update_status(self, status_msg, text, status_prefix="", reply_markup=None, is_batch=False):
        if status_prefix:
            full_text = f"{status_prefix}\n\n{text}"
        else:
            full_text = text
        # Mandatory delay to avoid Bale rate limits and ensure in-place editing
        await asyncio.sleep(1.1)
        # Use force_edit=True to ensure we don't send new messages for these internal steps
        return await edit_message(status_msg, full_text, reply_markup=reply_markup, show_cancel=not is_batch, force_edit=True)

    async def download_and_send_track(self, chat_id, track_id, user_id, status_msg=None,
                                     is_batch=False, album_cover_bytes=None, collection_id=None,
                                     selected_quality=None, track_name_hint=None, track_index=None,
                                     status_prefix="", reply_markup=None):

        # In batch mode, if no status_msg provided, create a track-specific one
        if status_msg is None:
            prefix = f"({track_index}) " if track_index else ""
            hint = f" {track_name_hint}" if track_name_hint else ""
            init_text = f"⏳ *{prefix}در حال آماده‌سازی دانلود{hint}...*"
            if status_prefix: init_text = f"{status_prefix}\n\n{init_text}"
            status_msg = await send_message(self.bot, chat_id, init_text, show_cancel=not is_batch)

        status_msg = await self._update_status(status_msg, "🔍 *در حال دریافت اطلاعات آهنگ...*", status_prefix, reply_markup, is_batch)
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            status_msg = await self._update_status(status_msg, "خطا در دریافت اطلاعات آهنگ.", status_prefix, reply_markup, is_batch)
            return status_msg, False

        track = track_data["results"][0]
        settings = await self.user_settings_service.get_settings(user_id)

        quality_value = selected_quality or settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        caption = self._build_caption(track, quality_value)

        # Check cache
        audio_cache = await get_cached_audio(track_id, quality=quality_value)
        if audio_cache:
            logger.info(f"Using cached audio for track {track_id} (quality: {quality_value}) -> {audio_cache}")
            try:
                status_msg = await self._update_status(status_msg, "📤 *در حال ارسال فایل از حافظه کش...*", status_prefix, reply_markup, is_batch)
                markup = self._build_audio_markup(track_id, track.get("trackViewUrl"), user_id=user_id)
                await self.bot.send_audio(chat_id, audio=audio_cache, caption=caption, reply_markup=InlineKeyboard(*markup))
                if not is_batch: await safe_delete(status_msg)
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''),
                                                 track.get('artistName', ''), track.get('collectionName', ''),
                                                 0, 'cache', quality_value)
                await self.error_notifier.check_and_clear_if_resolved(self.bot, test_success=True)
                return status_msg, True
            except Exception as e:
                logger.error(f"Cache send failed: {e}")
                if collection_id:
                    async def cancel_album(): self.album_tracker.cancel_download(user_id, collection_id)
                    await self.error_notifier.notify_upload_error(self.bot, str(e), cancel_album)

        if OFFLINE_MODE:
            status_msg = await self._update_status(status_msg, "بات در حالت آفلاین است.", status_prefix, reply_markup, is_batch)
            return status_msg, False

        # Download from YouTube
        cover_bytes = album_cover_bytes
        if settings.show_artwork and cover_bytes is None:
            status_msg = await self._update_status(status_msg, "🖼️ *در حال دریافت کاور آهنگ...*", status_prefix, reply_markup, is_batch)
            cover_bytes = await self.artwork_service.get_artwork_bytes(track.get('collectionId') or track_id, track.get('artworkUrl100'))

        video_url = None
        if isinstance(track_id, str) and track_id.startswith(("yt_", "sc_")):
            video_url = track.get("trackViewUrl")
            logger.info(f"Using direct URL for external track {track_id}: {video_url}")

        if not video_url:
            status_msg = await self._update_status(status_msg, "🔍 *در حال جستجوی منبع با کیفیت...*", status_prefix, reply_markup, is_batch)
            logger.info(f"Searching YouTube for track {track_id}: {track.get('trackName')} - {track.get('artistName')}")
            video_id = await search_youtube_track(track.get("trackName", ""), track.get("artistName", ""),
                                                track.get("collectionName", ""), track.get("releaseDate", "")[:4])

            if not video_id:
                status_msg = await self._update_status(status_msg, "لینک مناسبی یافت نشد.", status_prefix, reply_markup, is_batch)
                return status_msg, False

            video_url = f"https://music.youtube.com/watch?v={video_id}"
        temp_dir = None
        try:
            async with self.download_semaphore:
                if collection_id:
                    self.album_tracker.start_track(user_id, collection_id, track.get("trackName", ""))

                status_msg = await self._update_status(status_msg, f"⏳ *در حال دانلود با کیفیت {quality_value}kbps...*", status_prefix, reply_markup, is_batch)
                logger.info(f"Downloading from YouTube: {video_url} with quality {quality_value}")
                mp3_path = await download_audio(video_url, quality=quality_value)
                if not mp3_path: raise Exception("Download failed")

                temp_dir = os.path.dirname(mp3_path)
                status_msg = await self._update_status(status_msg, "🏷️ *در حال تگ‌گذاری فایل...*", status_prefix, reply_markup, is_batch)
                self.tagging_service.tag_mp3(Path(mp3_path), track, cover_bytes)

                status_msg = await self._update_status(status_msg, "☁️ *در حال آپلود روی سرورهای ابری...*", status_prefix, reply_markup, is_batch)

                markup = self._build_audio_markup(track_id, track.get("trackViewUrl"), user_id=user_id)
                with open(mp3_path, 'rb') as f:
                    msg = await self.bot.send_audio(chat_id, audio=f, caption=caption, reply_markup=InlineKeyboard(*markup))
                    if msg and track_id and not str(track_id).startswith(("yt_", "sc_", "sp_", "it_")):
                        await set_mirror('track', str(track_id), 'audioUrl',
                                         f'https://tapi.bale.ai/file/bot<token>/{msg.audio.id}',
                                         quality=quality_value)

                file_size = os.path.getsize(mp3_path)
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''),
                                                 track.get('artistName', ''), track.get('collectionName', ''),
                                                 file_size, 'youtube', quality_value)
                self.download_rate_limiter.record_download(user_id, quality_value)
                await self.error_notifier.check_and_clear_if_resolved(self.bot, test_success=True)
                if not is_batch: await safe_delete(status_msg)
                return status_msg, True
        except Exception as e:
            logger.error(f"Download error: {e}")
            retry_markup = [[InlineKeyboardButton(text="🔄 تلاش مجدد", callback_data=f"retry:download_retry:{track_id}:u{user_id}")]]
            # But since _update_status supports custom reply_markup
            status_msg = await self._update_status(status_msg, f"❌ خطا در دانلود {track.get('trackName', '')}", status_prefix, InlineKeyboard(*retry_markup), is_batch)
            cancel_cb = None
            if collection_id:
                async def cancel_album(): self.album_tracker.cancel_download(user_id, collection_id)
                cancel_cb = cancel_album
            await self.error_notifier.notify_upload_error(self.bot, str(e), cancel_cb)
            return status_msg, False
        finally:
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_caption(self, track, quality_value):
        track_id = track.get('trackId', '')
        is_sc = str(track_id).startswith("sc_")

        artist_id = track.get('artistId')
        artist_name = track.get('artistName')

        if is_sc:
            artist_link = artist_name
        else:
            if artist_name:
                artist_link = f"[{artist_name}]({generate_deep_link('artist', artist_id)})" if artist_id else artist_name
            else:
                artist_link = None

        coll_id = track.get('collectionId')
        coll_name = track.get('collectionName')
        if coll_name:
            coll_link = f"[{coll_name}]({generate_deep_link('collection', coll_id)})" if coll_id else coll_name
        else:
            coll_link = None

        track_name = track.get('trackName')
        if track_name:
            track_name_link = f"[{track_name}]({generate_deep_link('track', track_id)})"
        else:
            track_name_link = None

        duration_ms = int(track.get('trackTimeMillis') or 0)
        duration_text = format_duration(duration_ms) if duration_ms > 0 else None

        fields = {
            "🎵 نام آهنگ": track_name_link,
            "🎤 نام آپلودر" if is_sc else "🎤 نام هنرمند": artist_link,
            "💿 نام آلبوم": coll_link if not is_sc else None,
            "📅 سال انتشار": str(track.get('releaseDate', ''))[:4] if track.get('releaseDate') else None,
            "🎸 سبک": track.get('primaryGenreName'),
            "⏱️ مدت زمان": duration_text if not is_sc else None,
            "📀 کیفیت دانلود": f"{quality_value} kbps"
        }

        caption_lines = []
        for k, v in fields.items():
            if v and str(v).strip() and "Unknown" not in str(v) and "نامشخص" not in str(v) and "None" not in str(v):
                caption_lines.append(f"{k}: {v}")

        return "\n".join(caption_lines) + f"\n\n{FOOTER}"

    def _build_audio_markup(self, track_id, source_url=None, user_id=None):
        source_url = source_url or f"https://player.abraava.ir?id={track_id}"
        is_external = str(track_id).startswith(("yt_", "sc_", "sp_"))

        markup = []
        if not is_external:
            markup.append([InlineKeyboardButton(text="📂 نمایش در مینی اپ", web_app=f"https://player.abraava.ir?id={track_id}")])

        markup.append([InlineKeyboardButton(text="📋 کپی پیوند", copy_text=generate_deep_link("track", track_id))])
        markup.append([InlineKeyboardButton(text="🌐 اطلاعات بیشتر", url=source_url)])
        markup.append([create_close_button(user_id)])

        return markup
