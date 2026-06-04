import logging
import asyncio
import hashlib
import os
import io
import random
import time
import json
import pickle
import aiohttp
import aiosqlite
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Tuple
from dataclasses import dataclass
from enum import Enum
import signal
import sys
from balethon import Client
from balethon.objects import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboard
from ytmusicapi import ytmusic

from config import BOT_NAME, FOOTER, OFFLINE_MODE, ITEMS_PER_PAGE, BOT_TOKEN, DB_CHANNEL_ID, INFO_CHANNEL_ID, logger, \
    BROADCAST_CHANNELS, ITUNES_BASE_URL, API_BASE_URL, API_TOKEN
from crawlers.itunes import search_itunes, lookup_itunes, fetch_itunes, set_mirror, get_mirror, get_cached_audio, get_cached_artwork, get_cached_preview
from crawlers.utils import get_or_crawl_collection, \
    get_or_crawl_artist, get_track, get_or_crawl_collection_tracks, get_or_crawl_artist_collections
from crawlers.youtube import download_audio, search_youtube_track, get_artist_image
from utils import tag_mp3, send_error_with_retry, send_message, send_photo, send_audio, send_voice, \
    update_status_with_close, \
    reply_message, create_pagination_row, get_high_res_artwork, format_duration, generate_search_hash
import requests


# ============================================================================
# Download Quality Settings
# ============================================================================
class DownloadQuality(Enum):
    HIGH = "320"
    MEDIUM = "192"
    LOW = "128"
    ASK = "ask"

QUALITY_MULTIPLIER = {
    "320": 3,
    "192": 2,
    "128": 1
}

SUPPORTED_QUALITIES = ["320", "192", "128"]
DEFAULT_QUALITY = "192"

user_download_quality = {}
user_show_artwork = {}
user_quick_mode = {}
user_auto_download = {}
user_notifications = {}


# ============================================================================
# Bale Upload Error Notification System
# ============================================================================
class BaleUploadErrorNotifier:
    def __init__(self):
        self.notification_message_id = None
        self.error_active = False
        self.last_error_time = 0
        self.error_cooldown = 300

    async def notify_upload_error(self, bot: Client, error_message: str = "", album_download_callback: callable = None):
        if not INFO_CHANNEL_ID:
            return

        current_time = time.time()

        if self.error_active:
            logger.info("Upload error notification already active")
            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")
            return

        if current_time - self.last_error_time < self.error_cooldown:
            logger.info(f"Upload error notification on cooldown")
            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")
            return

        self.last_error_time = current_time

        notification_text = (
            "⚠️ *اختلال در سرویس آپلود بله* ⚠️\n\n"
            "در حال حاضر سرویس آپلود فایل پیام‌رسان بله با مشکل مواجه شده است.\n"
            "این مشکل از سمت بله می‌باشد و به محض رفع مشکل، ربات به حالت عادی بازخواهد گشت.\n\n"
            "✅ به محض رفع مشکل، این پیام حذف خواهد شد.\n\n"
            "#اطلاع_رسانی"
        )

        try:
            msg = await send_message(bot, INFO_CHANNEL_ID, notification_text)
            self.notification_message_id = msg.id
            self.error_active = True
            logger.warning(f"Bale upload error notification sent")

            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")

        except Exception as e:
            logger.error(f"Failed to send upload error notification: {e}")

    async def clear_upload_error_notification(self, bot: Client):
        if not INFO_CHANNEL_ID or not self.error_active:
            return

        try:
            await bot.delete_message(INFO_CHANNEL_ID, self.notification_message_id)
            logger.info("Bale upload error notification cleared")
        except Exception as e:
            logger.error(f"Failed to delete error notification: {e}")
        finally:
            self.error_active = False
            self.notification_message_id = None

    async def check_and_clear_if_resolved(self, bot: Client, test_success: bool = False):
        if self.error_active and test_success:
            await self.clear_upload_error_notification(bot)


bale_error_notifier = BaleUploadErrorNotifier()
album_upload_error_flag = {}


async def cancel_album_download_on_upload_error(user_id: int, collection_id: int, bot: Client, chat_id: int):
    key = (user_id, collection_id)
    album_upload_error_flag[key] = True
    album_tracker.cancel_download(user_id, collection_id)

    try:
        await send_message(bot, chat_id, "⚠️ *دانلود آلبوم به دلیل مشکل در سرویس آپلود بله متوقف شد*\nبه محض رفع مشکل می‌توانید مجدداً تلاش کنید.")
    except:
        pass


# ============================================================================
# API Client for PHP Backend
# ============================================================================
async def check_channel_membership(user_id: int, channel_id: str) -> bool:
    try:
        chat_member = await bot.get_chat_member(channel_id, user_id)
        if chat_member and chat_member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to check membership: {e}")
        return False


async def verify_all_memberships(user_id: int) -> tuple[bool, List[Dict]]:
    result = await api_client.get_required_channels()
    if not result.get('success'):
        return True, []

    channels = result.get('data', [])
    missing_channels = []

    for channel in channels:
        channel_id = channel.get('channel_id')
        if not await check_channel_membership(user_id, channel_id):
            missing_channels.append(channel)

    return len(missing_channels) == 0, missing_channels


class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None

    async def _request(self, action: str, data: Dict) -> Dict:
        if not self.session:
            self.session = aiohttp.ClientSession()

        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

        try:
            async with self.session.post(f"{self.base_url}?action={action}", json=data, headers=headers) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {'success': False, 'message': str(e)}

    async def register_user(self, user_data: Dict) -> Dict:
        return await self._request('register', user_data)

    async def get_user(self, user_id: int) -> Dict:
        return await self._request('get_user', {'user_id': user_id})

    async def get_user_settings(self, user_id: int) -> Dict:
        return await self._request('get_user_settings', {'user_id': user_id})

    async def update_quick_mode(self, user_id: int, enabled: bool) -> Dict:
        return await self._request('update_quick_mode', {'user_id': user_id, 'enabled': enabled})

    async def update_download_quality(self, user_id: int, quality: str) -> Dict:
        return await self._request('update_download_quality', {'user_id': user_id, 'quality': quality})

    async def update_show_artwork(self, user_id: int, show: bool) -> Dict:
        return await self._request('update_show_artwork', {'user_id': user_id, 'show': show})

    async def update_auto_download(self, user_id: int, enabled: bool) -> Dict:
        return await self._request('update_auto_download', {'user_id': user_id, 'enabled': enabled})

    async def update_notifications(self, user_id: int, enabled: bool) -> Dict:
        return await self._request('update_notifications', {'user_id': user_id, 'enabled': enabled})

    async def log_search(self, user_id: int, search_type: str, search_term: str, result_count: int) -> Dict:
        return await self._request('log_search', {
            'user_id': user_id,
            'search_type': search_type,
            'search_term': search_term,
            'result_count': result_count
        })

    async def log_download(self, user_id: int, track_id: str, track_name: str, artist_name: str,
                           album_name: str = '', file_size: int = 0, download_source: str = 'youtube', quality: str = '192') -> Dict:
        return await self._request('log_download', {
            'user_id': user_id,
            'track_id': track_id,
            'track_name': track_name,
            'artist_name': artist_name,
            'album_name': album_name,
            'file_size': file_size,
            'download_source': download_source,
            'quality': quality
        })

    async def log_album_download(self, user_id: int, collection_id: str, collection_name: str,
                                 artist_name: str, total_tracks: int, successful_tracks: int,
                                 failed_tracks: int) -> Dict:
        return await self._request('log_album', {
            'user_id': user_id,
            'collection_id': collection_id,
            'collection_name': collection_name,
            'artist_name': artist_name,
            'total_tracks': total_tracks,
            'successful_tracks': successful_tracks,
            'failed_tracks': failed_tracks
        })

    async def get_required_channels(self) -> Dict:
        return await self._request('get_required_channels', {})

    async def get_broadcast_channels(self) -> Dict:
        return await self._request('get_broadcast_channels', {})

    async def add_required_channel(self, channel_id: str, channel_username: str, channel_name: str,
                                   invite_link: str = '', order_position: int = 0) -> Dict:
        return await self._request('add_required_channel', {
            'channel_id': channel_id,
            'channel_username': channel_username,
            'channel_name': channel_name,
            'invite_link': invite_link,
            'order_position': order_position
        })

    async def remove_required_channel(self, channel_id: str) -> Dict:
        return await self._request('remove_required_channel', {'channel_id': channel_id})

    async def add_broadcast_channel(self, channel_id: str, channel_username: str, channel_name: str,
                                    keywords: str = '#اطلاع_رسانی #ابرآوا #اطلاعیه #تبلیغات') -> Dict:
        return await self._request('add_broadcast_channel', {
            'channel_id': channel_id,
            'channel_username': channel_username,
            'channel_name': channel_name,
            'keywords': keywords
        })

    async def remove_broadcast_channel(self, channel_id: str) -> Dict:
        return await self._request('remove_broadcast_channel', {'channel_id': channel_id})

    async def log_broadcast(self, message_id: str, channel_id: str, message_text: str,
                            sent_to: int, successful: int, failed: int) -> Dict:
        return await self._request('log_broadcast', {
            'message_id': message_id,
            'channel_id': channel_id,
            'message_text': message_text,
            'sent_to': sent_to,
            'successful': successful,
            'failed': failed
        })

    async def get_active_users(self, limit: int = None) -> Dict:
        return await self._request('get_active_users', {'limit': limit})


api_client = APIClient(API_BASE_URL, API_TOKEN)


# ============================================================================
# Broadcast System - Simple Auto Forward (Like Second Code)
# ============================================================================
# لیست ادمین‌ها
ADMIN_IDS = [234591600]  # آیدی شما اضافه شد


async def is_admin(user_id: int) -> bool:
    """بررسی ادمین بودن کاربر"""
    return user_id in ADMIN_IDS


async def process_broadcast_message(message: Message):
    """Process messages from broadcast channels and forward to all users"""
    # Only process channel messages
    if message.chat.type != "channel":
        return
    
    chat_id = str(message.chat.id)
    chat = await bot.get_chat(int(chat_id))
    chat_username = f"@{chat.username}" if chat.username else ""

    # Get broadcast channels from API
    result = await api_client.get_broadcast_channels()
    if not result.get('success'):
        return

    broadcast_channels = result.get('data', [])

    # Check if this channel is registered for broadcasting (by channel_id)
    is_broadcast_channel = False
    channel_config = None

    for channel in broadcast_channels:
        if str(channel.get('channel_id')) == chat_id:
            is_broadcast_channel = True
            channel_config = channel
            break

    if not is_broadcast_channel:
        return

    # Check if message contains broadcast keywords
    message_text = message.content or ""
    if message.caption:
        message_text = message.caption

    keywords = channel_config.get('keywords', '#اطلاع_رسانی #ابرآوا #اطلاعیه #تبلیغات')
    keyword_list = [kw.strip() for kw in keywords.split() if kw.strip()]

    should_broadcast = False
    for keyword in keyword_list:
        if keyword in message_text:
            should_broadcast = True
            break

    if not should_broadcast:
        return

    # Get all active users
    users_result = await api_client.get_active_users()
    if not users_result.get('success'):
        logger.error("Failed to get active users for broadcast")
        return

    users = users_result.get('data', [])

    # Send to all users
    successful = 0
    failed = 0

    for user in users:
        try:
            user_id = user.get('id')
            if user_id:
                # Forward the message
                await bot.forward_message(chat_id=user_id, message_id=message.id, from_chat_id=message.chat.id)
                successful += 1
                await asyncio.sleep(0.05)  # Small delay to avoid rate limiting
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user.get('user_id')}: {e}")
            failed += 1

    # Log broadcast
    await api_client.log_broadcast(
        message_id=str(message.id),
        channel_id=chat_id,
        message_text=message_text[:500],
        sent_to=len(users),
        successful=successful,
        failed=failed
    )

    logger.info(f"Broadcast sent: {successful} successful, {failed} failed")


# ============================================================================
# HTTP Session & Semaphores
# ============================================================================
HTTP_SESSION: Optional[aiohttp.ClientSession] = None
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(20)

MESSAGE_OWNER = {}
MESSAGE_OWNER_TTL = 600

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

SEARCH_CACHE_TTL = 600
SEARCH_CACHE = {}
SEARCH_CACHE_MAX_ITEMS = 100

user_active_downloads = set()
user_download_lock = asyncio.Lock()


async def acquire_user_download_lock(user_id: int) -> bool:
    async with user_download_lock:
        if user_id in user_active_downloads:
            return False
        user_active_downloads.add(user_id)
        return True


def release_user_download_lock(user_id: int):
    if user_id in user_active_downloads:
        user_active_downloads.remove(user_id)


# ============================================================================
# Rate Limiting
# ============================================================================
class RateLimiter:
    def __init__(self, max_requests: int = 30, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.users: Dict[int, List[Union[int, float]]] = {}
        self.global_count = 0
        self.global_reset = time.time()
        self.max_global = 30

    async def check_user(self, user_id: int) -> tuple[bool, int]:
        now = time.time()
        if now - self.global_reset > self.time_window:
            self.global_count = 0
            self.global_reset = now
        if self.global_count >= self.max_global:
            wait_time = int(self.time_window - (now - self.global_reset))
            return False, wait_time

        user_data = self.users.get(user_id)
        if not user_data or now - user_data[1] > self.time_window:
            user_data = [0, now]
            self.users[user_id] = user_data
        if user_data[0] >= self.max_requests:
            wait_time = int(self.time_window - (now - user_data[1]))
            return False, wait_time

        user_data[0] += 1
        self.global_count += 1
        return True, 0

    def get_user_remaining(self, user_id: int) -> int:
        now = time.time()
        user_data = self.users.get(user_id)
        if not user_data or now - user_data[1] > self.time_window:
            return self.max_requests
        return max(0, self.max_requests - user_data[0])


rate_limiter = RateLimiter(max_requests=30, time_window=60)


class DownloadRateLimiter:
    def __init__(self, max_downloads: int = 100, time_window: int = 3600):
        self.max_downloads = max_downloads
        self.time_window = time_window
        self.users: Dict[int, List[float]] = defaultdict(list)

    async def can_download(self, user_id: int, quality: str = "192") -> tuple[bool, int]:
        now = time.time()
        multiplier = QUALITY_MULTIPLIER.get(quality, 1)
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]

        total_used = len(self.users[user_id])
        available_slots = self.max_downloads - total_used

        if available_slots < multiplier:
            oldest = min(self.users[user_id]) if self.users[user_id] else now
            wait_seconds = int(self.time_window - (now - oldest))
            return False, wait_seconds
        return True, 0

    def record_download(self, user_id: int, quality: str = "192"):
        now = time.time()
        multiplier = QUALITY_MULTIPLIER.get(quality, 1)
        for _ in range(multiplier):
            self.users[user_id].append(now)

    def get_remaining(self, user_id: int) -> int:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]
        return max(0, self.max_downloads - len(self.users[user_id]))


download_rate_limiter = DownloadRateLimiter(max_downloads=100, time_window=3600)


# ============================================================================
# User Settings Management
# ============================================================================
def set_default_user_settings(user_id: int):
    user_quick_mode[user_id] = False
    user_download_quality[user_id] = DownloadQuality.MEDIUM
    user_show_artwork[user_id] = True
    user_auto_download[user_id] = False
    user_notifications[user_id] = True
    logger.info(f"Set default settings for user {user_id}")


async def load_user_settings(user_id: int):
    try:
        settings_result = await api_client.get_user_settings(user_id)
        if settings_result.get('success'):
            settings = settings_result.get('data', {})
            user_quick_mode[user_id] = bool(settings.get('quick_mode', False))
            user_show_artwork[user_id] = bool(settings.get('show_artwork', True))
            user_auto_download[user_id] = bool(settings.get('auto_download', False))
            user_notifications[user_id] = bool(settings.get('notifications', True))

            quality_str = settings.get('download_quality', '192')
            if quality_str == "320":
                user_download_quality[user_id] = DownloadQuality.HIGH
            elif quality_str == "192":
                user_download_quality[user_id] = DownloadQuality.MEDIUM
            elif quality_str == "128":
                user_download_quality[user_id] = DownloadQuality.LOW
            elif quality_str == "ask":
                user_download_quality[user_id] = DownloadQuality.ASK
            else:
                user_download_quality[user_id] = DownloadQuality.MEDIUM

            logger.info(f"Loaded settings for user {user_id}")
        else:
            set_default_user_settings(user_id)
    except Exception as e:
        logger.error(f"Error loading user settings for {user_id}: {e}")
        set_default_user_settings(user_id)


async def register_user(message: Message):
    user = message.author
    quality_value = user_download_quality.get(user.id, DownloadQuality.MEDIUM).value
    user_data = {
        'user_id': user.id,
        'username': user.username or '',
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'language_code': getattr(user, 'language_code', 'en'),
        'is_premium': getattr(user, 'is_premium', False),
        'is_bot': getattr(user, 'is_bot', False),
        'user_agent': message.content or '',
        'ip_address': '',
        'quick_mode': user_quick_mode.get(user.id, False),
        'download_quality': quality_value,
        'show_artwork': user_show_artwork.get(user.id, True),
        'auto_download': user_auto_download.get(user.id, False),
        'notifications': user_notifications.get(user.id, True)
    }

    result = await api_client.register_user(user_data)
    if result.get('success'):
        logger.info(f"User {user.id} registered/updated")
        await load_user_settings(user.id)
    else:
        logger.error(f"Failed to register user {user.id}: {result.get('message')}")
        set_default_user_settings(user.id)


# ============================================================================
# Album Download Tracker
# ============================================================================
@dataclass
class TrackDownloadStatus:
    name: str
    success: bool = False
    error: str = None
    order: int = 0
    start_time: float = 0
    duration: float = 0


class AlbumDownloadTracker:
    def __init__(self):
        self.active_downloads = {}
        self.download_locks = {}

    async def acquire_lock(self, user_id: int, collection_id: int) -> bool:
        key = (user_id, collection_id)
        if key not in self.download_locks:
            self.download_locks[key] = asyncio.Lock()
        try:
            await asyncio.wait_for(self.download_locks[key].acquire(), timeout=5.0)
            return True
        except asyncio.TimeoutError:
            return False

    def release_lock(self, user_id: int, collection_id: int):
        key = (user_id, collection_id)
        if key in self.download_locks and self.download_locks[key].locked():
            self.download_locks[key].release()

    def start_download(self, user_id: int, collection_id: int, status_msg, total_tracks: int, collection_name: str):
        key = (user_id, collection_id)
        self.active_downloads[key] = {
            "status_msg": status_msg,
            "tracks": [],
            "current_idx": 0,
            "total": total_tracks,
            "cancelled": False,
            "cancelled_time": 0,
            "collection_name": collection_name,
            "start_time": time.time(),
            "cover_bytes": None
        }

    def add_track(self, user_id: int, collection_id: int, track_name: str, order: int):
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return
        self.active_downloads[key]["tracks"].append(TrackDownloadStatus(name=track_name, order=order))

    def start_track(self, user_id: int, collection_id: int, track_name: str):
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return
        for track in self.active_downloads[key]["tracks"]:
            if track.name == track_name:
                track.start_time = time.time()
                break

    def set_cover_bytes(self, user_id: int, collection_id: int, cover_bytes: bytes):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key]["cover_bytes"] = cover_bytes

    def update_track_result(self, user_id: int, collection_id: int, track_name: str, success: bool, error_msg: str = None):
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return
        tracker = self.active_downloads[key]
        for track in tracker["tracks"]:
            if track.name == track_name:
                track.success = success
                track.error = error_msg
                track.duration = time.time() - track.start_time if track.start_time > 0 else 0
                break
        tracker["current_idx"] += 1

    def get_progress_text(self, user_id: int, collection_id: int) -> str:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return ""
        t = self.active_downloads[key]

        if t.get("cancelled", False):
            return f"⏹️ *در حال توقف دانلود آلبوم {t['collection_name']}...*"

        completed = sum(1 for tr in t["tracks"] if tr.success)
        failed = sum(1 for tr in t["tracks"] if not tr.success and tr.error is not None)
        elapsed = time.time() - t["start_time"]

        text = f"⬇️ *در حال دانلود آلبوم: {t['collection_name']}*\n\n"
        text += f"🎵 *پیشرفت:* {t['current_idx']}/{t['total']} قطعه\n"
        text += f"✅ *موفق:* {completed}\n"
        text += f"❌ *ناموفق:* {failed}\n\n"

        if t["current_idx"] < t["total"] and t["tracks"] and t["current_idx"] < len(t["tracks"]):
            current_track = t["tracks"][t["current_idx"]]
            text += f"🎤 *در حال دانلود:* {current_track.name}\n"

            if current_track.start_time > 0:
                track_elapsed = int(time.time() - current_track.start_time)
                text += f"⏱️ *زمان سپری شده:* {track_elapsed} ثانیه\n\n"
            else:
                text += f"\n"

        if t["current_idx"] > 0 and completed + failed > 0:
            avg_time = elapsed / (completed + failed)
            remaining_tracks = t["total"] - (completed + failed)
            eta = int(avg_time * remaining_tracks)
            if eta > 0:
                minutes = eta // 60
                seconds = eta % 60
                if minutes > 0:
                    text += f"⏱️ *زمان باقیمانده:* {minutes} دقیقه {seconds} ثانیه"
                else:
                    text += f"⏱️ *زمان باقیمانده:* {seconds} ثانیه"

        return text

    def get_simple_progress(self, user_id: int, collection_id: int, current_track_name: str, current_index: int) -> str:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return f"⬇️ *در حال دانلود آلبوم...*"

        t = self.active_downloads[key]

        if t.get("cancelled", False):
            return f"⏹️ *در حال توقف دانلود آلبوم {t['collection_name']}...*"

        text = f"⬇️ *در حال دانلود آلبوم {t['collection_name']}...*\n\n"
        text += f"🎵 *پیشرفت:* {current_index}/{t['total']} قطعه\n"
        text += f"🎤 *در حال دانلود:* {current_track_name}"

        return text

    def finish_download(self, user_id: int, collection_id: int, successful_tracks: int = 0, failed_tracks: int = 0):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            t = self.active_downloads[key]
            asyncio.create_task(api_client.log_album_download(
                user_id=user_id,
                collection_id=str(collection_id),
                collection_name=t.get('collection_name', ''),
                artist_name='',
                total_tracks=t.get('total', 0),
                successful_tracks=successful_tracks,
                failed_tracks=failed_tracks
            ))
            del self.active_downloads[key]
        self.release_lock(user_id, collection_id)

    def is_cancelled(self, user_id: int, collection_id: int) -> bool:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return True
        return self.active_downloads[key].get("cancelled", False)

    def cancel_download(self, user_id: int, collection_id: int):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key]["cancelled"] = True
            self.active_downloads[key]["cancelled_time"] = time.time()


album_tracker = AlbumDownloadTracker()


# ============================================================================
# Cache Functions with Quality Support
# ============================================================================
async def get_cached_audio_with_quality(track_id: int, quality: str = None) -> Optional[str]:
    try:
        if track_id:
            target_quality = quality or DEFAULT_QUALITY
            if target_quality not in SUPPORTED_QUALITIES:
                target_quality = DEFAULT_QUALITY

            data = await get_mirror('track', str(track_id), 'audioUrl', quality=target_quality)
            if data and data.get("mirrors", {}).get('audioUrl', False):
                cached_url = data["mirrors"]['audioUrl']['url']
                if cached_url and '<token>' in cached_url:
                    file_id = cached_url.split('<token>/')[1]
                    return file_id
                return cached_url
    except Exception as e:
        logger.error(f"Error getting cached audio: {e}")
    return None


async def get_cached_artwork_with_quality(entity_type: str, entity_id: int) -> Optional[str]:
    try:
        if entity_id:
            data = await get_mirror(entity_type, str(entity_id), 'artworkUrl')
            if data and data.get("mirrors", {}).get('artworkUrl', False):
                cached_url = data["mirrors"]['artworkUrl']['url']
                if cached_url and '<token>' in cached_url:
                    file_id = cached_url.split('<token>/')[1]
                    return file_id
                return cached_url
    except Exception as e:
        logger.error(f"Error getting cached artwork: {e}")
    return None


async def get_cached_preview_with_quality(track_id: int) -> Optional[str]:
    try:
        if track_id:
            data = await get_mirror('track', str(track_id), 'previewUrl')
            if data.get("mirrors", {}).get('previewUrl', False):
                cached_url = data["mirrors"]['previewUrl']['url']
                if cached_url and '<token>' in cached_url:
                    file_id = cached_url.split('<token>/')[1]
                    return file_id
                return cached_url
    except Exception as e:
        logger.error(f"Error getting cached preview: {e}")
    return None


# ============================================================================
# Artwork Sending with Error Handling and Retry
# ============================================================================
async def send_photo_with_retry(bot: Client, chat_id: int, photo_data, caption: str, 
                                 reply_markup=None, max_retries: int = 3,
                                 entity_type: str = None, entity_id: int = None,
                                 user_id: int = None) -> Optional[Message]:
    """
    Send photo with retry mechanism. If all retries fail with upload errors,
    ask user whether to retry with fresh download or send without artwork.
    """
    last_exception = None
    
    for attempt in range(1, max_retries + 1):
        try:
            # Check if photo_data is a file_id (string) or bytes
            if isinstance(photo_data, bytes):
                # Create a BytesIO object for uploading
                photo_io = io.BytesIO(photo_data)
                photo_io.name = "artwork.jpg"
                msg = await send_photo(bot, chat_id, photo=photo_io, caption=caption, reply_markup=reply_markup)
            else:
                msg = await send_photo(bot, chat_id, photo=photo_data, caption=caption, reply_markup=reply_markup)
            
            # Success - save to mirror if needed
            if msg and entity_type and entity_id:
                await set_mirror(entity_type, str(entity_id), 'artworkUrl',
                                 'https://tapi.bale.ai/file/bot<token>/' + str(msg.photo[0].id))
            
            return msg
            
        except Exception as e:
            error_str = str(e).lower()
            last_exception = e
            logger.warning(f"send_photo attempt {attempt}/{max_retries} failed: {error_str}")
            
            # Check if this is an upload-related error
            is_upload_error = any(keyword in error_str for keyword in ['upload', 'timeout', 'connection', 'network', 'file_id', 'photo'])
            
            if is_upload_error and attempt == max_retries:
                # All retries failed with upload error
                if user_id:
                    # Ask user what to do
                    await bale_error_notifier.notify_upload_error(bot, str(e))
                    
                    ask_text = (
                        "⚠️ *مشکل در آپلود تصویر کاور*\n\n"
                        "در حال حاضر سرویس آپلود تصاویر بله با مشکل مواجه شده است.\n\n"
                        "آیا می‌خواهید تصویر را دوباره دانلود کرده و تلاش مجدد کنیم؟\n"
                        "(در غیر این صورت پیام بدون تصویر ارسال می‌شود)"
                    )
                    
                    markup = [
                        [
                            InlineKeyboardButton(text="✅ بله، دوباره تلاش کن", callback_data=f"retry_artwork:{entity_type}:{entity_id}:{chat_id}")
                        ],
                        [
                            InlineKeyboardButton(text="❌ خیر، بدون تصویر بفرست", callback_data=f"skip_artwork:{chat_id}")
                        ]
                    ]
                    
                    # Store the caption and reply_markup for later use
                    temp_data = {
                        "caption": caption,
                        "reply_markup": reply_markup,
                        "original_callback": None
                    }
                    
                    # Send asking message
                    temp_msg = await send_message(bot, chat_id, ask_text, reply_markup=markup)
                    
                    # Store temporary data in a global dict for callback
                    pending_artwork_requests[chat_id] = {
                        "temp_msg_id": temp_msg.id,
                        "data": temp_data,
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "user_id": user_id
                    }
                    
                    return None
            
            if attempt < max_retries:
                wait_time = attempt * 2
                await asyncio.sleep(wait_time)
    
    raise last_exception if last_exception else Exception("Failed to send photo after multiple retries")


async def download_and_send_artwork(bot: Client, chat_id: int, artwork_url: str, caption: str,
                                     reply_markup=None, entity_type: str = None, entity_id: int = None,
                                     user_id: int = None) -> Optional[Message]:
    """
    Download artwork and send it with retry mechanism.
    """
    # First check cache
    if entity_type and entity_id:
        cached_artwork = await get_cached_artwork_with_quality(entity_type, entity_id)
        if cached_artwork:
            try:
                return await send_photo_with_retry(bot, chat_id, cached_artwork, caption, reply_markup,
                                                    entity_type=entity_type, entity_id=entity_id,
                                                    user_id=user_id, max_retries=2)
            except Exception as e:
                logger.error(f"Failed to send cached artwork: {e}")
                # Continue to download fresh
    
    # Download artwork
    for attempt in range(1):
        try:
            async with HTTP_SESSION.get(artwork_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    artwork_bytes = await resp.read()
                    return await send_photo_with_retry(bot, chat_id, artwork_bytes, caption, reply_markup,
                                                        entity_type=entity_type, entity_id=entity_id,
                                                        user_id=user_id, max_retries=1)
                else:
                    raise Exception(f"HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"Download artwork attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(attempt * 2)
            else:
                logger.error(f"Failed to download artwork after 3 attempts: {e}")
                raise


# ============================================================================
# Quality Selection - Simple Dialog
# ============================================================================
async def ask_quality_simple(chat_id: int, track_id: int = None, track_name: str = None, 
                              is_album: bool = False, collection_id: int = None, 
                              collection_name: str = None):
    
    if is_album:
        text = f"📀 *انتخاب کیفیت برای:*\n{collection_name}"
    else:
        text = f"🎵 *انتخاب کیفیت برای:*\n{track_name}"
    
    markup = [
        [
            InlineKeyboardButton("🎵 320", callback_data=f"q_320:{'album' if is_album else 'track'}:{collection_id if is_album else track_id}:{collection_name if is_album else ''}"),
            InlineKeyboardButton("🎶 192", callback_data=f"q_192:{'album' if is_album else 'track'}:{collection_id if is_album else track_id}:{collection_name if is_album else ''}"),
            InlineKeyboardButton("🎧 128", callback_data=f"q_128:{'album' if is_album else 'track'}:{collection_id if is_album else track_id}:{collection_name if is_album else ''}")
        ],
        [InlineKeyboardButton("🔙 انصراف", callback_data="ignore")]
    ]
    
    await send_message(bot, chat_id, text, reply_markup=markup)


# ============================================================================
# Search and Download Functions
# ============================================================================
async def quick_search_and_send(bot: Client, chat_id: int, user_id: int, term: str, original_message: Message = None):
    status_msg = await send_message(bot, chat_id, f"⚡ *جستجوی {term}...*")

    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)

        if results and results.get("resultCount", 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            if track_id:
                quality_setting = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
                
                if quality_setting == DownloadQuality.ASK:
                    await ask_quality_simple(chat_id, track_id=track_id, track_name=track.get('trackName', 'آهنگ'), is_album=False)
                    await status_msg.delete()
                else:
                    asyncio.create_task(download_and_send_single_track(bot, chat_id, track_id, user_id, selected_quality=quality_setting.value))
                    await status_msg.delete()

                await api_client.log_search(user_id, 'quick', term, 1)
            else:
                await send_error_with_retry(bot, chat_id, "نتیجه‌ای یافت نشد.", f"quick_retry:{term}", status_msg)
        else:
            await send_error_with_retry(bot, chat_id, "نتیجه‌ای یافت نشد.", f"quick_retry:{term}", status_msg)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"quick_retry:{term}", status_msg)


async def send_audio_with_retry(bot: Client, chat_id: int, audio_path: str, file_name: str, caption: str,
                                max_retries=2, track_id=None, user_id=None, collection_id=None, quality: str = None):
    last_exception = None
    abs_audio_path = os.path.abspath(str(audio_path))

    exists = await asyncio.to_thread(os.path.exists, abs_audio_path)
    if not exists:
        raise FileNotFoundError(f"File not found: {abs_audio_path}")

    markup = [[
        InlineKeyboardButton(
            text="📂 نمایش در مینی اپ",
            web_app="https://player.abraava.ir?id=" + str(track_id)
        )],
        [InlineKeyboardButton(
            text="📋 کپی پیوند",
            copy_text="https://player.abraava.ir?id=" + str(track_id)
        )
    ]]

    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_audio_path, 'rb') as audio_file:
                msg = await send_audio(bot, chat_id=chat_id, audio=audio_file, caption=caption, reply_markup=markup)

                if msg and track_id:
                    target_quality = quality or DEFAULT_QUALITY
                    await set_mirror(
                        'track', str(track_id), 'audioUrl',
                        'https://tapi.bale.ai/file/bot<token>/' + str(msg.audio.id),
                        quality=target_quality
                    )
                return msg

        except Exception as e:
            error_str = str(e)
            last_exception = e
            logger.warning(f"send_audio attempt {attempt}/{max_retries} failed: {error_str}")

            if any(keyword in error_str.lower() for keyword in ['upload', 'timeout', 'connection', 'network', 'file_id', 'audio']):
                cancel_callback = None
                if user_id and collection_id:
                    async def cancel_album():
                        await cancel_album_download_on_upload_error(user_id, collection_id, bot, chat_id)
                    cancel_callback = cancel_album
                await bale_error_notifier.notify_upload_error(bot, error_str, cancel_callback)

            if attempt < max_retries:
                wait_time = attempt * 2
                await asyncio.sleep(wait_time)
            else:
                raise

    raise last_exception if last_exception else Exception("آپلود failed")


async def get_album_artwork_from_cache(collection_id: int) -> Optional[bytes]:
    """Get album artwork from cache (collection mirror)"""
    try:
        cached_artwork = await get_cached_artwork_with_quality('collection', collection_id)
        if cached_artwork:
            # If it's a file_id, we need to download it to get bytes
            if isinstance(cached_artwork, str):
                if cached_artwork.startswith('http'):
                    async with HTTP_SESSION.get(cached_artwork) as resp:
                        if resp.status == 200:
                            return await resp.read()
                else:
                    # It's a file_id, we can't get bytes directly, but we can use it for sending
                    # Return the file_id as a special marker
                    return cached_artwork
    except Exception as e:
        logger.error(f"Error getting cached album artwork: {e}")
    return None


async def download_album_artwork(collection_id: int, collection_data: dict = None) -> Optional[bytes]:
    """Download album artwork from source and cache it"""
    try:
        if not collection_data:
            collection_data = await get_or_crawl_collection(collection_id, None, False)
            if collection_data:
                collection_data = collection_data['results'][0]
        
        if collection_data:
            cover_url = get_high_res_artwork(collection_data.get("artworkUrl100"), size=600)
            if cover_url and HTTP_SESSION:
                async with HTTP_SESSION.get(cover_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        artwork_bytes = await resp.read()
                        # Cache it to collection mirror
                        # Note: We'll cache it when sending successfully
                        return artwork_bytes
    except Exception as e:
        logger.error(f"Error downloading album artwork: {e}")
    return None


async def get_or_download_album_artwork(collection_id: int, collection_data: dict = None, 
                                         user_id: int = None, chat_id: int = None) -> Optional[Union[bytes, str]]:
    """Get album artwork from cache or download it"""
    # First try cache
    cached = await get_album_artwork_from_cache(collection_id)
    if cached:
        return cached
    
    # Download fresh
    artwork_bytes = await download_album_artwork(collection_id, collection_data)
    if artwork_bytes:
        return artwork_bytes
    
    return None


async def download_and_send_single_track(bot: Client, chat_id: int, track_id: int, user_id: int = None,
                                         status_msg: Message = None, is_batch: bool = False,
                                         album_cover_bytes: Union[bytes, str] = None, collection_id: int = None,
                                         selected_quality: str = None, album_artwork_from_collection: bool = True):
    if is_batch or status_msg is None:
        status_msg = await send_message(bot, chat_id, text="⏳ *در حال آماده‌سازی دانلود...*")

    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await send_error_with_retry(bot, chat_id, "خطا در دریافت اطلاعات آهنگ.", f"download_retry:{track_id}", status_msg)
        return

    track = track_data["results"][0]
    release_year = track.get("releaseDate", "").split("-")[0] if track.get("releaseDate") else ""

    if selected_quality:
        if selected_quality == "320":
            quality = DownloadQuality.HIGH
        elif selected_quality == "192":
            quality = DownloadQuality.MEDIUM
        else:
            quality = DownloadQuality.LOW
        quality_value = selected_quality
    else:
        quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
        quality_value = quality.value

    caption_parts = [
        f"🎵 *نام آهنگ:* {track.get('trackName', 'Unknown Title')}",
        f"🎤 *نام هنرمند:* {track.get('artistName', 'Unknown Artist')}",
    ]
    if track.get('collectionName'):
        caption_parts.append(f"💿 *نام آلبوم:* {track.get('collectionName')}")
    if release_year:
        caption_parts.append(f"📅 *سال انتشار:* {release_year}")
    if track.get('primaryGenreName'):
        caption_parts.append(f"🎸 *سبک:* {track.get('primaryGenreName')}")
    if track.get('trackExplicitness') == 'explicit':
        caption_parts.append(f"🔞 *Explicit:* بله")
    if track.get('trackTimeMillis'):
        duration_sec = int(track['trackTimeMillis']) // 1000
        minutes = duration_sec // 60
        seconds = duration_sec % 60
        caption_parts.append(f"⏱️ *مدت زمان:* {minutes}:{seconds:02d}")
    caption_parts.append(f"📀 *کیفیت دانلود:* {quality_value} kbps")
    caption = "\n".join(caption_parts)

    audio_cache = await get_cached_audio_with_quality(track_id, quality=quality_value)

    if audio_cache:
        try:
            await update_status_with_close(status_msg, f"📤 *در حال ارسال فایل از حافظه کش...*")
            
            markup = [[
                InlineKeyboardButton(
                    text="📂 نمایش در مینی اپ",
                    web_app="https://player.abraava.ir?id=" + str(track_id)
                )],[
                InlineKeyboardButton(
                    text="📋 کپی پیوند",
                    copy_text="https://player.abraava.ir?id=" + str(track_id)
                )
            ]]
            
            await send_audio(bot, chat_id, audio=audio_cache, caption=caption, reply_markup=markup)
            await status_msg.delete()
            await api_client.log_download(
                user_id=user_id, track_id=str(track_id), track_name=track.get('trackName', ''),
                artist_name=track.get('artistName', ''), album_name=track.get('collectionName', ''),
                file_size=0, download_source='cache', quality=quality_value
            )
            await bale_error_notifier.check_and_clear_if_resolved(bot, test_success=True)
            return
        except Exception as e:
            logger.error(f"Cache send failed: {e}, will re-download")
            if user_id and collection_id:
                async def cancel_album():
                    await cancel_album_download_on_upload_error(user_id, collection_id, bot, chat_id)
                await bale_error_notifier.notify_upload_error(bot, str(e), cancel_album)

    if OFFLINE_MODE:
        await send_error_with_retry(bot, chat_id, "بات در حالت آفلاین است.", f"download_retry:{track_id}", status_msg)
        return

    t_name = track.get("trackName", "Unknown Title")
    ye = track.get("releaseDate", "").split("-")[0]
    a_name = track.get("artistName", "Unknown Artist")
    collection_name = track.get("collectionName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100", track.get("artworkUrl")), size=600)

    await update_status_with_close(status_msg, "🔍 *در حال جستجوی منبع با کیفیت...*")

    try:
        video_id = await search_youtube_track(t_name, a_name, collection_name, ye)
        if not video_id:
            await send_error_with_retry(bot, chat_id, "لینک مناسبی یافت نشد.", f"download_retry:{track_id}", status_msg)
            return

        video_url = f"https://music.youtube.com/watch?v={video_id}"
        await update_status_with_close(status_msg, "⏳ *در حال آماده‌سازی دانلود...*")

        mp3_path_str = None
        temp_dir_to_clean = None
        try:
            async with DOWNLOAD_SEMAPHORE:
                if collection_id:
                    album_tracker.start_track(user_id, collection_id, t_name)

                await update_status_with_close(status_msg, f"⏳ *در حال دانلود با کیفیت {quality_value}kbps...*")
                mp3_path_str = await download_audio(video_url, quality=quality_value)
                temp_dir_to_clean = os.path.dirname(mp3_path_str)

                if not mp3_path_str or not os.path.exists(mp3_path_str):
                    await send_error_with_retry(bot, chat_id, "دانلود با شکست مواجه شد.", f"download_retry:{track_id}", status_msg)
                    return

                file_size_mb = os.path.getsize(mp3_path_str) / (1024 * 1024)

                cover_bytes = album_cover_bytes
                show_artwork = user_show_artwork.get(user_id, True)

                # If we're in album download mode and album_cover_bytes is provided, use it
                if show_artwork and cover_bytes is None and cover_url and HTTP_SESSION and not album_artwork_from_collection:
                    # Only download from track if not in album mode
                    try:
                        await update_status_with_close(status_msg, f"🖼️ *در حال دریافت کاور آلبوم...*")
                        async with HTTP_SESSION.get(cover_url) as resp:
                            if resp.status == 200:
                                cover_bytes = await resp.read()
                    except:
                        pass

                await asyncio.get_event_loop().run_in_executor(None, tag_mp3, mp3_path_str, track, cover_bytes)
                await update_status_with_close(status_msg, f"☁️ *در حال آپلود روی سرورهای ابری...*")

                await send_audio_with_retry(bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption,
                                            track_id=str(track['trackId']), user_id=user_id,
                                            collection_id=collection_id, quality=quality_value)

                await api_client.log_download(
                    user_id=user_id, track_id=str(track_id), track_name=t_name, artist_name=a_name,
                    album_name=collection_name, file_size=int(file_size_mb * 1024 * 1024),
                    download_source='youtube', quality=quality_value
                )
                download_rate_limiter.record_download(user_id, quality_value)

                try:
                    await status_msg.delete()
                except:
                    pass

        except Exception as e:
            await send_error_with_retry(bot, chat_id, f"خطا در دانلود: {str(e)[:100]}", f"download_retry:{track_id}", status_msg)
        finally:
            if temp_dir_to_clean and os.path.exists(temp_dir_to_clean):
                try:
                    import shutil
                    shutil.rmtree(temp_dir_to_clean, ignore_errors=True)
                except:
                    pass

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"download_retry:{track_id}", status_msg)


async def send_voice_preview(bot: Client, chat_id: int, track_id: int, user_id: int = None):
    status_msg = await send_message(bot, chat_id, "⏳ *در حال دریافت پیش‌نمایش...*")

    try:
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            await send_error_with_retry(bot, chat_id, "اطلاعات آهنگ یافت نشد.", f"preview_retry:{track_id}", status_msg)
            return

        track = track_data["results"][0]
        preview_url = track.get("previewUrl")

        if not preview_url:
            await send_error_with_retry(bot, chat_id, "پیش‌نمایشی موجود نیست.", f"preview_retry:{track_id}", status_msg)
            return

        preview_cache = await get_cached_preview_with_quality(track_id)
        if preview_cache:
            try:
                await send_voice(bot, chat_id, voice=preview_cache, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*")
                await status_msg.delete()
                return
            except Exception as e:
                logger.error(f"Cache preview send failed: {e}")

        async with HTTP_SESSION.get(preview_url) as resp:
            if resp.status == 200:
                preview_data = io.BytesIO(await resp.read())
                preview_data.name = f"preview_{track_id}.mp3"

                msg = await send_voice(bot, chat_id, voice=preview_data, caption=f"🎧 *پیش‌نمایش آهنگ {track.get('trackName')}*")

                if msg and track_id:
                    await set_mirror('track', str(track_id), 'previewUrl',
                                     'https://tapi.bale.ai/file/bot<token>/' + str(msg.voice.id))

                await status_msg.delete()
            else:
                await send_error_with_retry(bot, chat_id, "دریافت پیش‌نمایش با خطا مواجه شد.", f"preview_retry:{track_id}", status_msg)

    except Exception as e:
        logger.error(f"Failed to send preview: {e}")
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"preview_retry:{track_id}", status_msg)


async def download_and_send_album(bot: Client, chat_id: int, collection_id: int, user_id: int,
                                  collection_name: str, tracks: List[dict], status_msg: Message,
                                  selected_quality: str = None):
    if not await album_tracker.acquire_lock(user_id, collection_id):
        await update_status_with_close(status_msg, "❌ *در حال حاضر دانلود این آلبوم در حال انجام است*\nلطفاً چند لحظه صبر کنید.")
        album_tracker.finish_download(user_id, collection_id, 0, 0)
        release_user_download_lock(user_id)
        return

    album_tracker.start_download(user_id, collection_id, status_msg, len(tracks), collection_name)

    for idx, track in enumerate(tracks, 1):
        album_tracker.add_track(user_id, collection_id, track.get('trackName', 'Unknown'), idx)

    cancel_markup = [[InlineKeyboardButton(text="❌ لغو دانلود آلبوم", callback_data=f"cancel_album:{user_id}:{collection_id}")]]

    await update_status_with_close(status_msg, f"⬇️ *در حال دانلود آلبوم {collection_name}...*\n\n🎵 *آماده‌سازی...*",
                                   reply_markup=cancel_markup, no=True)

    album_cover_bytes = None
    show_artwork = user_show_artwork.get(user_id, True)

    if show_artwork and tracks:
        # Get album artwork from collection cache or download it
        try:
            await update_status_with_close(status_msg, f"🖼️ *در حال دریافت کاور آلبوم {collection_name}...*", no=True)
            album_artwork = await get_or_download_album_artwork(collection_id, None, user_id, chat_id)
            
            if album_artwork:
                if isinstance(album_artwork, bytes):
                    album_cover_bytes = album_artwork
                    album_tracker.set_cover_bytes(user_id, collection_id, album_cover_bytes)
                    logger.info(f"Album artwork loaded for collection {collection_id}")
                else:
                    # It's a file_id from cache, we can use it directly when sending
                    album_cover_bytes = album_artwork
                    album_tracker.set_cover_bytes(user_id, collection_id, album_cover_bytes)
        except Exception as e:
            logger.error(f"Failed to get album artwork: {e}")

    success_count = 0
    failed_tracks = []
    stopped_by_rate_limit = False
    is_cancelled_by_user = False

    if selected_quality:
        quality_value = selected_quality
    else:
        quality_value = user_download_quality.get(user_id, DownloadQuality.MEDIUM).value

    for idx, track in enumerate(tracks, 1):
        if album_tracker.is_cancelled(user_id, collection_id):
            is_cancelled_by_user = True
            await update_status_with_close(status_msg, f"⏹️ *در حال توقف دانلود آلبوم {collection_name}...*",
                                           reply_markup=None, no=True)
            await asyncio.sleep(0.5)
            break

        track_id = track.get('trackId')
        track_name = track.get('trackName', 'Unknown')

        progress_text = f"⬇️ *در حال دانلود آلبوم {collection_name}...*\n\n"
        progress_text += f"🎵 *پیشرفت:* {idx-1}/{len(tracks)} قطعه\n"
        progress_text += f"🎤 *در حال دانلود:* {track_name}"

        await update_status_with_close(status_msg, progress_text, reply_markup=cancel_markup, no=True)

        can_dl, wait_sec = await download_rate_limiter.can_download(user_id, quality_value)
        if not can_dl:
            stopped_by_rate_limit = True
            error_msg = f"محدودیت دانلود: {wait_sec} ثانیه صبر کنید"
            album_tracker.update_track_result(user_id, collection_id, track_name, False, error_msg)
            failed_tracks.append({"name": track_name, "error": error_msg})
            break

        try:
            # Pass the album cover bytes to the track download function
            await download_and_send_single_track(bot, chat_id, track_id, user_id, status_msg,
                                                 is_batch=True, album_cover_bytes=album_cover_bytes,
                                                 collection_id=collection_id, selected_quality=quality_value,
                                                 album_artwork_from_collection=True)
            album_tracker.update_track_result(user_id, collection_id, track_name, True)
            success_count += 1
        except Exception as e:
            error_msg = str(e)[:100]
            album_tracker.update_track_result(user_id, collection_id, track_name, False, error_msg)
            failed_tracks.append({"name": track_name, "error": error_msg})

        await asyncio.sleep(0.5)

    if is_cancelled_by_user:
        try:
            await status_msg.delete()
        except:
            pass

        final_text = f"⏹️ *دانلود آلبوم {collection_name} متوقف شد*\n\n"
        final_text += f"🎵 *جمع کل:* {len(tracks)} قطعه\n"
        final_text += f"✅ *موفق:* {success_count}\n"
        if failed_tracks:
            final_text += f"❌ *ناموفق:* {len(failed_tracks)}\n\n"
            if success_count > 0:
                final_text += "⚠️ *قطعات دانلود شده:*\n"
                for ft in failed_tracks[:5]:
                    final_text += f"🔸 {ft['name']}\n"
                if len(failed_tracks) > 5:
                    final_text += f"... و {len(failed_tracks) - 5} قطعه دیگر\n"

        await send_message(bot, chat_id, final_text)

        album_tracker.finish_download(user_id, collection_id, success_count, len(failed_tracks))
        release_user_download_lock(user_id)
        return

    try:
        await status_msg.delete()
    except:
        pass

    final_text = f"✅ *دانلود آلبوم {collection_name} با موفقیت کامل شد*\n\n"
    final_text += f"🎵 *جمع کل:* {len(tracks)} قطعه\n"
    final_text += f"✅ *موفق:* {success_count}\n"
    if failed_tracks:
        final_text += f"❌ *ناموفق:* {len(failed_tracks)}\n\n"
        final_text += "⚠️ *قطعات ناموفق:*\n"
        for ft in failed_tracks[:5]:
            final_text += f"🔸 {ft['name']}\n"
        if len(failed_tracks) > 5:
            final_text += f"... و {len(failed_tracks) - 5} قطعه دیگر\n"
    if stopped_by_rate_limit:
        final_text += "\n🚫 *توقف به دلیل محدودیت دانلود (کیفیت بالا مصرف بیشتری دارد)*"

    await send_message(bot, chat_id, final_text)

    album_tracker.finish_download(user_id, collection_id, success_count, len(failed_tracks))
    release_user_download_lock(user_id)


# ============================================================================
# Display Functions
# ============================================================================
async def show_artist_page(chat_id: int, artist_id: int, page: int = 1,
                           message_to_edit: Optional[Message] = None, owner_id: int = None, force=False, is_pagination: bool = False):
    status_msg = None
    if is_pagination:
        status_msg = await send_message(bot, chat_id, "📄 *در حال بارگذاری اطلاعات...*")
    else:
        status_msg = await send_message(bot, chat_id, "🔄 *در حال پردازش اطلاعات هنرمند...*")

    try:
        artist_data = await get_or_crawl_artist(artist_id=artist_id, status_msg=status_msg, force=force)
        if not artist_data:
            await send_error_with_retry(bot, chat_id, "هنرمند مورد نظر یافت نشد.", f"artist_retry:{artist_id}", status_msg)
            return
        artist_data = artist_data['results'][0]
        artist_image = get_artist_image(artist_data.get('artistName'))

        text = f"🎤 *نام هنرمند:* {artist_data.get('artistName', 'نامشخص')}\n"
        text += f"🎭 *سبک:* {artist_data.get('primaryGenreName', 'نامشخص')}\n"

        collections_data = await get_or_crawl_artist_collections(artist_id)
        collections = collections_data["results"] if collections_data else []

        markup = []
        if collections:
            total_items = len(collections)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_items = collections[start_idx:end_idx]

            text += f"\n📀 *آلبوم‌ها (مجموع {total_items} آلبوم):*\n"
            for collection in page_items:
                if collection['wrapperType'] == 'collection':
                    btn_text = f"📀 {collection.get('collectionName', 'نامشخص')[:40]} - {collection.get('artistName', 'نامشخص')[:30]}"
                    markup.append([InlineKeyboardButton(text=btn_text, callback_data=f"collection:{collection['collectionId']}:1")])

            if total_pages > 1:
                pagination_row = create_pagination_row(f"artist:{artist_id}", page, total_pages)
                markup.append(pagination_row)

        markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])

        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup,
                           owner_id=owner_id, artwork_url=artist_image, artist_id=artist_id, delete_old=is_pagination)

        if status_msg:
            try:
                await status_msg.delete()
            except:
                pass

    except Exception as e:
        if status_msg:
            await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"artist_retry:{artist_id}", status_msg)
        else:
            logger.error(f"Error in show_artist_page: {e}")


async def show_collection_page(chat_id: int, collection_id: int, page: int = 1,
                               message_to_edit: Optional[Message] = None, owner_id: int = None, force=False, is_pagination: bool = False):
    status_msg = None
    if is_pagination:
        status_msg = await send_message(bot, chat_id, "📄 *در حال بارگذاری اطلاعات...*")
    else:
        status_msg = await send_message(bot, chat_id, "🔄 *در حال پردازش اطلاعات آلبوم...*")

    try:
        collection_data = await get_or_crawl_collection(collection_id, status_msg, force)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)
        tracks = tracks_data["results"] if tracks_data else []
        if not collection_data:
            await send_error_with_retry(bot, chat_id, "آلبوم مورد نظر یافت نشد.", f"collection_retry:{collection_id}", status_msg)
            return
        collection_data = collection_data['results'][0]
        release_date = collection_data.get('releaseDate', 'نامشخص')[:10] if collection_data.get('releaseDate') else 'نامشخص'

        text = f"📀 *نام آلبوم:* {collection_data.get('collectionName', 'نامشخص')}\n"
        text += f"🎤 *نام هنرمند:* {collection_data.get('artistName', 'نامشخص')}\n"
        text += f"📅 *سال انتشار:* {release_date}\n"

        markup = []
        if tracks:
            total_items = len(tracks)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_items = tracks[start_idx:end_idx]

            text += f"\n🎵 *لیست قطعات (مجموع {total_items} قطعه):*\n"
            for i, track in enumerate(page_items, start_idx + 1):
                track_time = track.get('trackTimeMillis', 0)
                if isinstance(track_time, str):
                    track_time = int(track_time) if track_time.isdigit() else 0
                duration = format_duration(track_time)
                text += f"{i}. {track.get('trackName', 'نامشخص')} - {track.get('artistName', 'نامشخص')} ({duration})\n"

            for track in page_items:
                if track['wrapperType'] == 'track':
                    btn_text = f"🎵 {track.get('trackName', 'نامشخص')[:35]} - {track.get('artistName', 'نامشخص')[:25]}"
                    markup.append([InlineKeyboardButton(text=btn_text, callback_data=f"track:{track['trackId']}")])

            if total_pages > 1:
                pagination_row = create_pagination_row(f"collection:{collection_id}", page, total_pages)
                markup.append(pagination_row)

            chat = await bot.get_chat(chat_id)
            if chat.type != "group" and chat.type != "supergroup" and tracks:
                markup.append([InlineKeyboardButton(text="⬇️ دانلود کل آلبوم", callback_data=f"download_album:{collection_id}")])

        if collection_data.get("artistId"):
            markup.append([InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{collection_data['artistId']}:1")])

        markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:collection:{collection_id}")])

        artwork_url = get_high_res_artwork(collection_data.get("artworkUrl100"))

        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup,
                           artwork_url=artwork_url, cache_id=collection_id, owner_id=owner_id, delete_old=is_pagination)

        if status_msg:
            try:
                await status_msg.delete()
            except:
                pass

    except Exception as e:
        if status_msg:
            await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"collection_retry:{collection_id}", status_msg)
        else:
            logger.error(f"Error in show_collection_page: {e}")


async def show_track_page(chat_id: int, track_id: int, message_to_edit: Optional[Message] = None, owner_id: int = None):
    status_msg = await send_message(bot, chat_id, "🔄 *در حال بارگذاری اطلاعات آهنگ...*")

    try:
        data = await get_track(track_id, status_msg)
        if not data or not data.get("results"):
            await send_error_with_retry(bot, chat_id, "آهنگ مورد نظر یافت نشد.", f"track_retry:{track_id}", status_msg)
            return
        track = data["results"][0]
        duration = format_duration(track.get('trackTimeMillis', 0))
        release_date = track.get('releaseDate', 'نامشخص')[:10] if track.get('releaseDate') else 'نامشخص'

        text = f"🎵 *نام آهنگ:* {track.get('trackName', 'نامشخص')}\n"
        text += f"🎤 *نام هنرمند:* {track.get('artistName', 'نامشخص')}\n"
        text += f"💿 *نام آلبوم:* {track.get('collectionName', 'نامشخص')}\n"
        text += f"⏱️ *مدت زمان:* {duration}\n"
        text += f"📅 *سال انتشار:* {release_date}\n"

        markup = []
        
        download_btn = [InlineKeyboardButton(text="⬇️ دانلود", callback_data=f"download:{track_id}")]
        if track.get("previewUrl"):
            download_btn.append(InlineKeyboardButton(text="🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"))
        markup.append(download_btn)

        links = []
        if track.get('collectionId'):
            links.append(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"collection:{track['collectionId']}:1"))
        if track.get('artistId'):
            links.append(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"))
        if links:
            markup.append(links)

        artwork_url = get_high_res_artwork(track.get("artworkUrl", track.get("artworkUrl100")))

        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup, artwork_url=artwork_url,
                           cache_id=track.get('collectionId'), owner_id=owner_id, delete_old=False)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"track_retry:{track_id}", status_msg)


async def handle_search_command(chat_id: int, user_id: int, type_: str, term: str, original_message: Message = None,
                                owner_id: int = None):
    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}

    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجوی {type_fa_map.get(type_)}: {term}...*")

    try:
        results = {}
        if not OFFLINE_MODE:
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            entity = entity_map.get(type_)
            itunes_results = await search_itunes(term, entity=entity, limit=50)
            if itunes_results and itunes_results.get("resultCount", 0) > 0:
                results = itunes_results

        if results and results.get("resultCount", 0) > 0:
            await send_search_page(chat_id, type_, term, results, 1, owner_id=owner_id or user_id)
            await status_msg.delete()
            await api_client.log_search(user_id, type_, term, results.get("resultCount", 0))
        else:
            await send_error_with_retry(bot, chat_id, f"هیچ نتیجه‌ای برای '{term}' یافت نشد.", f"search_retry:{type_}:{term}", status_msg)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"search_retry:{type_}:{term}", status_msg)


async def send_search_page(chat_id: int, type_: str, term: str, results: dict, page: int,
                           message_to_edit: Optional[Message] = None, owner_id: int = None, is_pagination: bool = False):
    status_msg = None
    if is_pagination:
        status_msg = await send_message(bot, chat_id, "📄 *در حال بارگذاری اطلاعات...*")

    try:
        results_list = results["results"]
        total_items = len(results_list)
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = results_list[start_idx:end_idx]
        type_fa_map = {"artist": "هنرمند", "collection": "آلبوم", "track": "آهنگ"}

        markup = []
        header = f"📋 *نتایج جستجو برای {type_fa_map.get(type_, type_)}: {term}*\nتعداد کل: {total_items} مورد"

        for item in page_items:
            wrapper = item.get("wrapperType")
            if wrapper == "artist":
                btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
                callback = f"artist:{item['artistId']}:1"
            elif wrapper == "collection":
                btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:40]} - {item.get('artistName', 'نامشخص')[:30]}"
                callback = f"collection:{item['collectionId']}:1"
            elif wrapper == "track":
                btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:40]} - {item.get('artistName', 'نامشخص')[:30]}"
                callback = f"track:{item['trackId']}"
            else:
                continue
            markup.append([InlineKeyboardButton(text=btn_text, callback_data=callback)])

        if total_pages > 1:
            search_id = generate_search_hash(type_, term)
            await store_search_cache(search_id, type_, term, results, owner_id)
            pagination_row = create_pagination_row(f"page:search:{search_id}:{type_}", page, total_pages)
            markup.append(pagination_row)

        refine_term = term
        markup.append([InlineKeyboardButton("🔍 آلبوم‌ها", f"refine:album:{refine_term}"),
                       InlineKeyboardButton("🔍 هنرمندان", f"refine:artist:{refine_term}"),
                       InlineKeyboardButton("🔍 آهنگ‌ها", f"refine:track:{refine_term}")])

        await edit_or_send(bot, chat_id, message_to_edit, header, markup=markup,
                           owner_id=owner_id, delete_old=is_pagination)

        if status_msg:
            try:
                await status_msg.delete()
            except:
                pass

    except Exception as e:
        if status_msg:
            await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", None, status_msg)
        else:
            logger.error(f"Error in send_search_page: {e}")


async def edit_or_send(bot: Client, chat_id: int, message_to_edit: Optional[Message], text: str,
                       markup=None, artwork_url: str = None, cache_id=None, owner_id=None, artist_id=None, delete_old=False):
    if markup is None:
        markup = []

    msg = None
    show_artwork = user_show_artwork.get(owner_id, True) if owner_id else True

    if artwork_url and show_artwork:
        try:
            entity_type = "artist" if artist_id else "collection"
            entity_id = cache_id or artist_id
            
            # Use the new send_photo_with_retry function
            msg = await send_photo_with_retry(
                bot, chat_id, artwork_url, text, markup,
                entity_type=entity_type, entity_id=entity_id,
                user_id=owner_id, max_retries=3
            )
            
            # If send_photo_with_retry returned None (meaning user chose to skip artwork or we're waiting for response)
            if msg is None:
                # Check if we're waiting for user response in the callback
                return None
                
        except Exception as e:
            logger.error(f"Failed to send photo with retry: {e}, sending without artwork")
            msg = await send_message(bot, chat_id, text=text, reply_markup=markup, no=True)
    else:
        msg = await send_message(bot, chat_id, text, reply_markup=markup)

    if owner_id and msg and msg.chat.type in ["group", "supergroup"]:
        set_message_owner(msg.id, owner_id)

    if message_to_edit and delete_old:
        try:
            if message_to_edit.id in MESSAGE_OWNER:
                MESSAGE_OWNER.pop(message_to_edit.id, None)
            await message_to_edit.delete()
        except Exception as e:
            pass

    return msg


async def store_search_cache(search_id: str, type_: str, term: str, results: dict, owner_id: int):
    if len(SEARCH_CACHE) >= SEARCH_CACHE_MAX_ITEMS:
        oldest = min(SEARCH_CACHE.items(), key=lambda x: x[1]["timestamp"])
        SEARCH_CACHE.pop(oldest[0])
    SEARCH_CACHE[search_id] = {
        "type": type_,
        "term": term,
        "results": results,
        "owner_id": owner_id,
        "timestamp": time.time()
    }


async def get_search_cache(search_id: str) -> Optional[Dict]:
    data = SEARCH_CACHE.get(search_id)
    if data and time.time() - data["timestamp"] <= SEARCH_CACHE_TTL:
        return data
    if data:
        SEARCH_CACHE.pop(search_id, None)
    return None


def set_message_owner(message_id: int, owner_id: int):
    MESSAGE_OWNER[message_id] = (owner_id, time.time())


def get_message_owner(message_id: int) -> Optional[int]:
    data = MESSAGE_OWNER.get(message_id)
    if data:
        owner_id, ts = data
        if time.time() - ts <= MESSAGE_OWNER_TTL:
            return owner_id
        else:
            MESSAGE_OWNER.pop(message_id, None)
    return None


# Global dictionary for pending artwork retry requests
pending_artwork_requests = {}


async def retry_artwork_send(chat_id: int, entity_type: str, entity_id: int, user_id: int):
    """Retry sending artwork after user confirmation"""
    # Get original data
    request_data = pending_artwork_requests.get(chat_id, {})
    temp_msg_id = request_data.get("temp_msg_id")
    data = request_data.get("data", {})
    
    # Delete the asking message
    if temp_msg_id:
        try:
            await bot.delete_message(chat_id, temp_msg_id)
        except:
            pass
    
    # Clear pending request
    pending_artwork_requests.pop(chat_id, None)
    
    # Try to download and send artwork fresh
    status_msg = await send_message(bot, chat_id, "🖼️ *در حال تلاش مجدد برای دریافت و ارسال تصویر کاور...*")
    
    try:
        # Get artwork URL based on entity type
        artwork_url = None
        if entity_type == "artist":
            artist_data = await get_or_crawl_artist(artist_id=entity_id, status_msg=status_msg, force=True)
            if artist_data:
                artwork_url = get_artist_image(artist_data['results'][0].get('artistName'))
        elif entity_type == "collection":
            collection_data = await get_or_crawl_collection(entity_id, status_msg, force=True)
            if collection_data:
                artwork_url = get_high_res_artwork(collection_data['results'][0].get("artworkUrl100"))
        
        if artwork_url:
            # Download and send artwork
            for attempt in range(1, 4):
                try:
                    async with HTTP_SESSION.get(artwork_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            artwork_bytes = await resp.read()
                            # Try to send with the same caption and markup
                            msg = await send_photo(bot, chat_id, photo=io.BytesIO(artwork_bytes), 
                                                    caption=data.get("caption", ""), 
                                                    reply_markup=data.get("reply_markup"))
                            if msg and entity_type and entity_id:
                                await set_mirror(entity_type, str(entity_id), 'artworkUrl',
                                                 'https://tapi.bale.ai/file/bot<token>/' + str(msg.photo[0].id))
                            await status_msg.delete()
                            return
                except Exception as e:
                    if attempt < 3:
                        await asyncio.sleep(attempt * 2)
                    else:
                        raise
        else:
            raise Exception("Artwork URL not found")
            
    except Exception as e:
        logger.error(f"Failed to send artwork on retry: {e}")
        await status_msg.delete()
        # Send without artwork
        await send_message(bot, chat_id, text=data.get("caption", ""), reply_markup=data.get("reply_markup"), no=True)


# ============================================================================
# Settings Message Functions (ONLY for PM)
# ============================================================================
async def show_settings_message(chat_id: int, user_id: int, message_to_delete: Message = None):
    quick_mode = user_quick_mode.get(user_id, False)
    quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    show_artwork = user_show_artwork.get(user_id, True)
    auto_download = user_auto_download.get(user_id, False)
    notifications = user_notifications.get(user_id, True)

    if quality == DownloadQuality.ASK:
        quality_text = "هر بار بپرس"
    else:
        quality_text = f"{quality.value} kbps"

    settings_text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت سریع:* {'فعال' if quick_mode else 'غیرفعال'}\n\n"
        f"🎵 *کیفیت دانلود:* {quality_text}\n\n"
        f"🖼️ *نمایش کاور:* {'فعال' if show_artwork else 'غیرفعال'}\n\n"
        f"⚡ *دانلود خودکار:* {'فعال' if auto_download else 'غیرفعال'}\n\n"
        f"🔔 *دریافت اعلان:* {'فعال' if notifications else 'غیرفعال'}\n\n"
        f"📊 برای مشاهده آمار دقیق، روی دکمه «آمار من» کلیک کنید."
    )

    markup = [
        [InlineKeyboardButton(text=f"{'✅' if quick_mode else '❌'} حالت سریع", callback_data="menu_quick_mode")],
        [InlineKeyboardButton(text=f"🎵 کیفیت دانلود ({quality_text})", callback_data="show_quality_menu")],
        [InlineKeyboardButton(text=f"{'🖼️' if show_artwork else '🚫'} نمایش کاور", callback_data="menu_artwork")],
        [InlineKeyboardButton(text=f"{'⚡' if auto_download else '⏸️'} دانلود خودکار", callback_data="menu_auto_download")],
        [InlineKeyboardButton(text=f"{'🔔' if notifications else '🔕'} دریافت اعلان", callback_data="menu_notifications")],
        [InlineKeyboardButton(text="📊 آمار من", callback_data="show_stats")],
    ]

    msg = await send_message(bot, chat_id, settings_text, reply_markup=markup)

    if message_to_delete:
        try:
            await message_to_delete.delete()
        except:
            pass

    return msg


async def show_confirmation_menu(callback_query: CallbackQuery, setting_type: str, current_value: bool, display_name: str, emoji: str = "⚙️"):
    status_text = "فعال" if current_value else "غیرفعال"
    new_status = not current_value
    new_status_text = "غیرفعال" if current_value else "فعال"

    confirmation_text = (
        f"{emoji} *تغییر تنظیمات*\n\n"
        f"تنظیمات: *{display_name}*\n"
        f"وضعیت فعلی: *{status_text}*\n\n"
        f"آیا می‌خواهید این تنظیم را به *{new_status_text}* تغییر دهید؟"
    )

    markup = [
        [InlineKeyboardButton(text="✅ بله، تغییر کن", callback_data=f"confirm_{setting_type}:{int(new_status)}")],
        [InlineKeyboardButton(text="❌ خیر، انصراف", callback_data="back_to_settings")],
    ]

    updating_msg = await send_message(bot, callback_query.message.chat.id, "🔄 *در حال بارگذاری...*")

    try:
        await callback_query.message.delete()
    except:
        pass

    msg = await send_message(bot, callback_query.message.chat.id, confirmation_text, reply_markup=markup)

    try:
        await updating_msg.delete()
    except:
        pass


async def update_settings_message(callback_query: CallbackQuery, user_id: int):
    updating_msg = await send_message(bot, callback_query.message.chat.id, "🔄 *در حال بروزرسانی تنظیمات...*")

    try:
        await callback_query.message.delete()
    except:
        pass

    await show_settings_message(callback_query.message.chat.id, user_id)

    try:
        await updating_msg.delete()
    except:
        pass


async def show_quality_menu(callback_query: CallbackQuery, user_id: int):
    current_quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)

    updating_msg = await send_message(bot, callback_query.message.chat.id, "🔄 *در حال بارگذاری منوی کیفیت...*")

    try:
        await callback_query.message.delete()
    except:
        pass

    quality_text = (
        "🎵 *تنظیم کیفیت دانلود*\n\n"
        "کیفیت پیش‌فرض را انتخاب کنید:\n\n"
        "🎵 **۳۲۰ kbps** - کیفیت استودیویی (مصرف ۳ واحد)\n"
        "🎶 **۱۹۲ kbps** - کیفیت عالی (مصرف ۲ واحد)\n"
        "🎧 **۱۲۸ kbps** - کیفیت خوب (مصرف ۱ واحد)\n"
        "❓ **هر بار بپرس** - قبل از هر دانلود کیفیت را انتخاب کنید\n\n"
        f"کیفیت فعلی شما: {current_quality.value if current_quality != DownloadQuality.ASK else 'هر بار بپرس'}"
    )

    markup = [
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.HIGH else ''}🎵 ۳۲۰ kbps", callback_data="set_quality:320")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.MEDIUM else ''}🎶 ۱۹۲ kbps", callback_data="set_quality:192")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.LOW else ''}🎧 ۱۲۸ kbps", callback_data="set_quality:128")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.ASK else ''}❓ هر بار بپرس", callback_data="set_quality:ask")],
        [InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="back_to_settings")],
    ]

    msg = await send_message(bot, callback_query.message.chat.id, quality_text, reply_markup=markup)

    try:
        await updating_msg.delete()
    except:
        pass


async def show_stats_message(callback_query: CallbackQuery, user_id: int):
    remaining = rate_limiter.get_user_remaining(user_id)
    quick_mode = user_quick_mode.get(user_id, False)
    downloads_remaining = download_rate_limiter.get_remaining(user_id)
    current_quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    show_artwork = user_show_artwork.get(user_id, True)
    auto_download = user_auto_download.get(user_id, False)
    notifications = user_notifications.get(user_id, True)

    user_data = await api_client.get_user(user_id)
    total_searches = user_data.get('data', {}).get('total_searches', 0) if user_data.get('success') else 0
    total_downloads = user_data.get('data', {}).get('total_downloads', 0) if user_data.get('success') else 0

    quality_text = current_quality.value if current_quality != DownloadQuality.ASK else "هر بار بپرس"

    stats_text = (
        f"📊 *آمار و تنظیمات شما*\n\n"
        f"🔍 *محدودیت جستجو:*\n"
        f"   🔹 باقی‌مانده: {remaining} درخواست\n"
        f"   🔹 حداکثر: {rate_limiter.max_requests} در دقیقه\n\n"
        f"⬇️ *محدودیت دانلود:*\n"
        f"   🔹 باقی‌مانده: {downloads_remaining} واحد\n"
        f"   🔹 حداکثر: {download_rate_limiter.max_downloads} واحد در ساعت\n\n"
        f"⚙️ *تنظیمات فعال:*\n"
        f"   🔹 حالت سریع: {'فعال' if quick_mode else 'غیرفعال'}\n"
        f"   🔹 کیفیت دانلود: {quality_text}\n"
        f"   🔹 نمایش کاور: {'فعال' if show_artwork else 'غیرفعال'}\n"
        f"   🔹 دانلود خودکار: {'فعال' if auto_download else 'غیرفعال'}\n"
        f"   🔹 دریافت اعلان: {'فعال' if notifications else 'غیرفعال'}\n\n"
        f"📈 *آمار کلی:*\n"
        f"   🔹 جستجوها: {total_searches}\n"
        f"   🔹 دانلودها: {total_downloads}"
    )

    markup = [[InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="back_to_settings")]]

    updating_msg = await send_message(bot, callback_query.message.chat.id, "🔄 *در حال بارگذاری آمار...*")

    try:
        await callback_query.message.delete()
    except:
        pass

    msg = await send_message(bot, callback_query.message.chat.id, stats_text, reply_markup=markup)

    try:
        await updating_msg.delete()
    except:
        pass


# ============================================================================
# Message Validation
# ============================================================================
def is_valid_message(message) -> bool:
    if len(message.content or "") > 100:
        return False
    if hasattr(message, 'photo') and message.photo:
        return False
    if hasattr(message, 'video') and message.video:
        return False
    if hasattr(message, 'document') and message.document:
        return False
    if hasattr(message, 'audio') and message.audio:
        return False
    if hasattr(message, 'voice') and message.voice:
        return False
    if hasattr(message, 'forward_from') and message.forward_from:
        return False
    return True


async def parse_search_query(text: str) -> Optional[tuple[str, str]]:
    text = text.strip()
    if not text:
        return None

    if text.startswith("/search"):
        text = text[7:].strip()
    elif text.startswith("/album"):
        text = text[6:].strip()
        return "album", text
    elif text.startswith("/track"):
        text = text[6:].strip()
        return "track", text
    elif text.startswith("/artist"):
        text = text[7:].strip()
        return "artist", text
    elif text.startswith("/quick"):
        text = text[6:].strip()
        return "quick", text
    else:
        return "track", text


# ============================================================================
# Bale Bot Initialization & Handlers
# ============================================================================
bot = Client(token=BOT_TOKEN)


@bot.on_initialize()
async def on_initialize():
    global HTTP_SESSION
    HTTP_SESSION = aiohttp.ClientSession()
    await api_client._request('get_required_channels', {})
    
    await register_channel_members()
    await api_client._request('get_required_channels', {})
    logger.info(f'ربات "{BOT_NAME}" با موفقیت روشن شد')
    logger.info(f"محدودیت جستجو: {rate_limiter.max_requests} درخواست در دقیقه")
    logger.info(f"محدودیت دانلود: {download_rate_limiter.max_downloads} واحد در ساعت")
    logger.info(f"سیستم فوروارد خودکار برودکست فعال شد")


@bot.on_shutdown()
async def on_shutdown():
    global HTTP_SESSION
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()
    if api_client.session and not api_client.session.closed:
        await api_client.session.close()
    logger.info("ربات خاموش شد")


@bot.on_message()
async def handle_message(message):
    # Skip bot's own messages
    if message.author.is_bot:
        return

    # Process broadcast messages from channels (AUTO FORWARD - like second code)
    if message.chat.type == "channel" and message.chat.id == INFO_CHANNEL_ID:
        await process_broadcast_message(message)
        return

    # Register user on any message
    await register_user(message)

    if message.chat.type == "channel":
        return

    if "abraava" in str(message.author.username):
        return

    is_group = message.chat.type in ["group", "supergroup"]
    msg_text = message.content or ""
    user_id = message.author.id
    chat_id = message.chat.id
    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention not in msg_text:
            return
        if not is_valid_message(message):
            return
        msg_text = msg_text.replace(bot_mention, "").strip()
        if len(msg_text) > 100:
            await reply_message(message, "⚠️ *متن پیام خیلی طولانی است*\n\nحداکثر ۱۰۰ کاراکتر مجاز است.")
            return
    if (not msg_text.startswith("/start")):
        is_member, missing = await verify_all_memberships(user_id)
        if not is_member:
            channels_text = ""
            for ch in missing:
                channel_name = ch.get('channel_name', ch.get('channel_username', ch.get('channel_id')))
                invite_link = ch.get('invite_link', '')
                if invite_link:
                    channels_text += f"[{channel_name}]({invite_link})\n"
                else:
                    channels_text += f"{channel_name}\n"
            await reply_message(message, f"⚠️ *برای استفاده از ربات باید در کانال‌های زیر عضو شوید:*\n\n{channels_text}\n\nپس از عضویت، دوباره تلاش کنید.")
            return

    

    if msg_text.startswith("/start"):
        welcome_text = (
            f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
            f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n"
            f"فقط کافیه اسم آهنگ رو بگی، خودم بلدم چیکار کنم 😉\n\n"
            f"🆘 راهنما: /help"
        )
        if INFO_CHANNEL_ID:
            welcome_text += f"\n\n📢 *کانال اطلاع‌رسانی:* ble.ir/join/4T95Zt7P5X"
        await reply_message(message, welcome_text)

    elif msg_text.startswith("/help"):
        if is_group:
            await reply_message(message, "🎵 *راهنمای استفاده*\n\nبرای جستجو، نام آهنگ/آلبوم/هنرمند را به همراه منشن ربات ارسال کنید.\nمثال: `@BotName آهنگ جدید`")
        else:
            await reply_message(message,
                                f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
                                f"🔍 *دستورات جستجو:*\n"
                                f"🔹 `/track [نام آهنگ]` - جستجوی آهنگ\n"
                                f"🔹 `/album [نام آلبوم]` - جستجوی آلبوم\n"
                                f"🔹 `/artist [نام هنرمند]` - جستجوی هنرمند\n"
                                f"🔹 `/quick [نام آهنگ]` - دانلود سریع\n\n"
                                f"⚙️ تنظیمات: /settings\n"
                                f"📊 آمار: /stats"
                                )

    elif msg_text.startswith("/settings"):
        if is_group:
            await reply_message(message, "⚙️ تنظیمات فقط در پیوی در دسترس است.\nلطفاً به پیوی ربات مراجعه کنید.")
        else:
            await show_settings_message(chat_id, user_id)

    elif msg_text.startswith("/stats"):
        if is_group:
            await reply_message(message, "📊 آمار فقط در پیوی در دسترس است.\nلطفاً به پیوی ربات مراجعه کنید.")
        else:
            remaining = rate_limiter.get_user_remaining(user_id)
            downloads_remaining = download_rate_limiter.get_remaining(user_id)
            user_data = await api_client.get_user(user_id)
            total_searches = user_data.get('data', {}).get('total_searches', 0) if user_data.get('success') else 0
            total_downloads = user_data.get('data', {}).get('total_downloads', 0) if user_data.get('success') else 0

            await reply_message(message,
                                f"📊 *آمار شما*\n\n"
                                f"🔍 جستجوی باقی‌مانده: {remaining}/{rate_limiter.max_requests}\n"
                                f"⬇️ دانلود باقی‌مانده: {downloads_remaining}/{download_rate_limiter.max_downloads}\n\n"
                                f"📈 آمار کلی:\n"
                                f"🔹 جستجوها: {total_searches}\n"
                                f"🔹 دانلودها: {total_downloads}"
                                )

    elif msg_text.startswith("/about"):
        await reply_message(message,
                            f"ℹ️ *درباره {BOT_NAME}*\n\n"
                            f"ربات دانلود موزیک با قابلیت جستجو در iTunes و دانلود از YouTube Music\n\n"
                            f"✨ *ویژگی‌ها:*\n"
                            f"🔹 دانلود با کیفیت ۳۲۰/۱۹۲/۱۲۸ kbps\n"
                            f"🔹 دانلود آلبوم به صورت یکجا\n"
                            f"🔹 تگ‌گذاری خودکار (کاور و اطلاعات)\n"
                            f"🔹 قابلیت غیرفعال کردن کاور برای سرعت بیشتر\n"
                            f"🔹 دانلود خودکار در حالت سریع\n"
                            f"🔹 سیستم سهمیه دانلود بر اساس کیفیت"
                            )

    else:
        result = await parse_search_query(msg_text)
        if result:
            type_, term = result
            if type_ == "quick" or user_quick_mode.get(user_id, False):
                await quick_search_and_send(bot, chat_id, user_id, term, message)
            else:
                await handle_search_command(chat_id, user_id, type_, term, message, user_id)


# ============================================================================
# Callback Handler
# ============================================================================
@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id
    is_group = callback_query.message.chat.type in ["group", "supergroup"]
    
    if data == "close":
        await callback_query.message.delete()
        return
    
    if data == "ignore":
        await bot.answer_callback_query(callback_query.id)
        return
    
    # Handle artwork retry/skip callbacks
    if data.startswith("retry_artwork:"):
        parts = data.split(":")
        entity_type = parts[1]
        entity_id = int(parts[2])
        target_chat_id = int(parts[3])
        
        if user_id != callback_query.author.id:
            await bot.answer_callback_query(callback_query.id, "❌ شما دسترسی ندارید", show_alert=True)
            return
        
        await bot.answer_callback_query(callback_query.id, "🔄 در حال تلاش مجدد...")
        await retry_artwork_send(target_chat_id, entity_type, entity_id, user_id)
        await callback_query.message.delete()
        return
    
    if data.startswith("skip_artwork:"):
        parts = data.split(":")
        target_chat_id = int(parts[1])
        
        # Get original data
        request_data = pending_artwork_requests.get(target_chat_id, {})
        temp_msg_id = request_data.get("temp_msg_id")
        data_dict = request_data.get("data", {})
        
        # Delete the asking message
        if temp_msg_id:
            try:
                await bot.delete_message(target_chat_id, temp_msg_id)
            except:
                pass
        
        # Clear pending request
        pending_artwork_requests.pop(target_chat_id, None)
        
        # Send without artwork
        await send_message(bot, target_chat_id, text=data_dict.get("caption", ""), 
                          reply_markup=data_dict.get("reply_markup"), no=True)
        await bot.answer_callback_query(callback_query.id, "✅ پیام بدون تصویر ارسال شد")
        await callback_query.message.delete()
        return

    # ========== کیفیت انتخاب شده برای دانلود ==========
    if data.startswith("q_320:") or data.startswith("q_192:") or data.startswith("q_128:"):
        parts = data.split(":")
        quality = parts[0][2:]
        type_ = parts[1]
        id_ = int(parts[2])
        name = parts[3] if len(parts) > 3 else ""
        
        if type_ == "track":
            await bot.answer_callback_query(callback_query.id, f"🎵 در حال دانلود با کیفیت {quality}kbps...")
            await callback_query.message.delete()
            asyncio.create_task(download_and_send_single_track(bot, chat_id, id_, user_id, selected_quality=quality))
        else:
            await bot.answer_callback_query(callback_query.id, f"📀 در حال دانلود آلبوم با کیفیت {quality}kbps...")
            await callback_query.message.delete()
            
            collection_data = await get_or_crawl_collection(id_, None, False)
            tracks_data = await get_or_crawl_collection_tracks(id_)
            tracks = tracks_data["results"] if tracks_data else []
            
            if not tracks:
                await send_message(bot, chat_id, "❌ قطعه‌ای یافت نشد")
                return
            
            collection_name = name or (collection_data['results'][0].get('collectionName', 'آلبوم') if collection_data else 'آلبوم')
            status_msg = await send_message(bot, chat_id, f"🎵 *شروع دانلود آلبوم: {collection_name}*")
            asyncio.create_task(download_and_send_album(bot, chat_id, id_, user_id, collection_name, tracks, status_msg, selected_quality=quality))
        return

    # ========== تنظیمات منوها (فقط در پیوی) ==========


    if data == "menu_quick_mode":
        current = user_quick_mode.get(user_id, False)
        await show_confirmation_menu(callback_query, "quick_mode", current, "حالت سریع", "⚡")
        return

    if data == "menu_artwork":
        current = user_show_artwork.get(user_id, True)
        await show_confirmation_menu(callback_query, "show_artwork", current, "نمایش کاور", "🖼️")
        return

    if data == "menu_auto_download":
        current = user_auto_download.get(user_id, False)
        await show_confirmation_menu(callback_query, "auto_download", current, "دانلود خودکار", "⚡")
        return

    if data == "menu_notifications":
        current = user_notifications.get(user_id, True)
        await show_confirmation_menu(callback_query, "notifications", current, "دریافت اعلان", "🔔")
        return

    if data.startswith("confirm_quick_mode:"):
        value = int(data.split(":")[1])
        user_quick_mode[user_id] = bool(value)
        await api_client.update_quick_mode(user_id, bool(value))
        await update_settings_message(callback_query, user_id)
        await bot.answer_callback_query(callback_query.id, "✅ تنظیمات ذخیره شد")
        return

    if data.startswith("confirm_show_artwork:"):
        value = int(data.split(":")[1])
        user_show_artwork[user_id] = bool(value)
        await api_client.update_show_artwork(user_id, bool(value))
        await update_settings_message(callback_query, user_id)
        await bot.answer_callback_query(callback_query.id, "✅ تنظیمات ذخیره شد")
        return

    if data.startswith("confirm_auto_download:"):
        value = int(data.split(":")[1])
        user_auto_download[user_id] = bool(value)
        await api_client.update_auto_download(user_id, bool(value))
        await update_settings_message(callback_query, user_id)
        await bot.answer_callback_query(callback_query.id, "✅ تنظیمات ذخیره شد")
        return

    if data.startswith("confirm_notifications:"):
        value = int(data.split(":")[1])
        user_notifications[user_id] = bool(value)
        await api_client.update_notifications(user_id, bool(value))
        await update_settings_message(callback_query, user_id)
        await bot.answer_callback_query(callback_query.id, "✅ تنظیمات ذخیره شد")
        return

    if data == "show_stats":
        await show_stats_message(callback_query, user_id)
        return

    if data == "show_quality_menu":
        await show_quality_menu(callback_query, user_id)
        return

    if data.startswith("set_quality:"):
        quality_value = data.split(":")[1]
        if quality_value == "320":
            user_download_quality[user_id] = DownloadQuality.HIGH
        elif quality_value == "192":
            user_download_quality[user_id] = DownloadQuality.MEDIUM
        elif quality_value == "128":
            user_download_quality[user_id] = DownloadQuality.LOW
        elif quality_value == "ask":
            user_download_quality[user_id] = DownloadQuality.ASK
        await api_client.update_download_quality(user_id, quality_value)
        await update_settings_message(callback_query, user_id)
        await bot.answer_callback_query(callback_query.id, f"✅ کیفیت به {quality_value if quality_value != 'ask' else 'هر بار بپرس'} تغییر کرد")
        return

    if data == "back_to_settings":
        await update_settings_message(callback_query, user_id)
        return

    # ========== دکمه‌های معمولی ==========
    if data.startswith("retry:"):
        retry_data = data[6:]
        if retry_data.startswith("search_retry:"):
            _, type_, term = retry_data.split(":", 2)
            await handle_search_command(chat_id, user_id, type_, term, owner_id=user_id)
        elif retry_data.startswith("download_retry:"):
            _, track_id = retry_data.split(":")
            asyncio.create_task(download_and_send_single_track(bot, chat_id, int(track_id), user_id))
        elif retry_data.startswith("preview_retry:"):
            _, track_id = retry_data.split(":")
            asyncio.create_task(send_voice_preview(bot, chat_id, int(track_id), user_id))
        elif retry_data.startswith("quick_retry:"):
            _, term = retry_data.split(":", 1)
            await quick_search_and_send(bot, chat_id, user_id, term)
        try:
            await callback_query.message.delete()
        except:
            pass
        return

    if data.startswith("cancel_album:"):
        parts = data.split(":")
        if len(parts) >= 3:
            owner_id_from_cb = int(parts[1])
            collection_id = int(parts[2])
            if user_id != owner_id_from_cb:
                await bot.answer_callback_query(callback_query.id, "❌ شما مالک نیستید", show_alert=True)
                return
            album_tracker.cancel_download(owner_id_from_cb, collection_id)
            await bot.answer_callback_query(callback_query.id, "⏹️ در حال توقف دانلود آلبوم...")
        return

    try:
        parts = data.split(":")
        if data.startswith("page:search:"):
            search_id = parts[2]
            type_ = parts[3]
            page = int(parts[4])
            cached = await get_search_cache(search_id)
            if cached:
                if is_group and cached["owner_id"] != user_id:
                    await bot.answer_callback_query(callback_query.id, "❌ مالک شما نیستید", show_alert=True)
                    return
                await send_search_page(chat_id, cached["type"], cached["term"], cached["results"], page,
                                       callback_query.message, owner_id=cached["owner_id"], is_pagination=True)
            else:
                await bot.answer_callback_query(callback_query.id, "⏳ نتایج منقضی شده", show_alert=True)
        elif data.startswith("refine:"):
            entity = parts[1]
            term = parts[2]
            await handle_search_command(chat_id, user_id, entity, term, owner_id=user_id)
        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            is_pagination = len(parts) > 2 and parts[2].isdigit() and page > 1
            await show_artist_page(chat_id, artist_id, page, callback_query.message, user_id, is_pagination=is_pagination)
        elif data.startswith("collection:"):
            collection_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            is_pagination = len(parts) > 2 and parts[2].isdigit() and page > 1
            await show_collection_page(chat_id, collection_id, page, callback_query.message, user_id, is_pagination=is_pagination)
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track_page(chat_id, track_id, callback_query.message, user_id)
        elif data.startswith("download:"):
            track_id = int(parts[1])
            quality_setting = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
            
            if quality_setting == DownloadQuality.ASK:
                track_data = await get_track(track_id)
                if track_data and track_data.get("results"):
                    track_name = track_data["results"][0].get('trackName', 'آهنگ')
                    await ask_quality_simple(chat_id, track_id=track_id, track_name=track_name, is_album=False)
                    await bot.answer_callback_query(callback_query.id, "🎵 کیفیت مورد نظر را انتخاب کنید")
                    return
            else:
                can_dl, wait_sec = await download_rate_limiter.can_download(user_id, quality_setting.value)
                if not can_dl:
                    await bot.answer_callback_query(callback_query.id, f"⏳ محدودیت: {wait_sec} ثانیه", show_alert=True)
                    return
                await bot.answer_callback_query(callback_query.id, "🎵 در حال پردازش...")
                asyncio.create_task(download_and_send_single_track(bot, chat_id, track_id, user_id))

        elif data.startswith("download_album:"):
            collection_id = int(parts[1])
            if is_group:
                await bot.answer_callback_query(callback_query.id, "❌ دانلود آلبوم در گروه ممنوع", show_alert=True)
                return
            
            quality_setting = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
            
            if quality_setting == DownloadQuality.ASK:
                collection_data = await get_or_crawl_collection(collection_id, None, False)
                collection_name = collection_data['results'][0].get('collectionName', 'آلبوم') if collection_data else 'آلبوم'
                await ask_quality_simple(chat_id, is_album=True, collection_id=collection_id, collection_name=collection_name)
                await bot.answer_callback_query(callback_query.id, "🎵 کیفیت مورد نظر را انتخاب کنید")
            else:
                await bot.answer_callback_query(callback_query.id, f"📀 در حال آماده‌سازی دانلود آلبوم...")
                
                collection_data = await get_or_crawl_collection(collection_id, None, False)
                tracks_data = await get_or_crawl_collection_tracks(collection_id)
                tracks = tracks_data["results"] if tracks_data else []
                
                if not tracks:
                    await send_message(bot, chat_id, "❌ قطعه‌ای یافت نشد")
                    return
                
                collection_name = collection_data['results'][0].get('collectionName', 'آلبوم') if collection_data else 'آلبوم'
                status_msg = await send_message(bot, chat_id, f"🎵 *شروع دانلود آلبوم: {collection_name}*")
                asyncio.create_task(download_and_send_album(bot, chat_id, collection_id, user_id, collection_name, tracks, status_msg))

        elif data.startswith("preview:"):
            track_id = int(parts[1])
            asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
        elif data.startswith("recrawl:"):
            type_ = parts[1]
            id_ = int(parts[2])
            if type_ == "artist":
                await show_artist_page(chat_id, id_, 1, callback_query.message, user_id, force=True)
            elif type_ == "collection":
                await show_collection_page(chat_id, id_, 1, callback_query.message, user_id, force=True)

    except Exception as e:
        logger.error(f"خطا: {e}")
        await bot.answer_callback_query(callback_query.id, "❌ خطا", show_alert=True)


def signal_handler(signum, frame):
    sys.exit(0)


async def get_all_channel_members(channel_id: int) -> List[Dict]:
    """Get all members from a channel with their details"""
    members = []
    try:
        offset = 0
        limit = 200
        while True:
            chat_members = await bot.get_chat_members(channel_id, offset=offset, limit=limit)
            if not chat_members:
                break
            for member in chat_members:
                user = member.user
                if not user.is_bot:
                    members.append({
                        'user_id': user.id,
                        'username': user.username or '',
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or '',
                        'language_code': getattr(user, 'language_code', 'en'),
                        'is_premium': getattr(user, 'is_premium', False),
                    })
            offset += limit
            await asyncio.sleep(0.5)
            if len(chat_members) < limit:
                break
    except Exception as e:
        logger.error(f"Failed to get channel members: {e}")
    return members


async def register_channel_members():
    """Automatically register all members of INFO_CHANNEL on startup"""
    if not INFO_CHANNEL_ID:
        logger.warning("INFO_CHANNEL_ID not set, skipping auto-register")
        return
    
    logger.info("Starting auto-registration of channel members...")
    
    members = await get_all_channel_members(INFO_CHANNEL_ID)
    
    if not members:
        logger.warning("No members found in info channel")
        return
    
    registered_count = 0
    failed_count = 0
    
    for member in members:
        try:
            # Check if user exists
            user_result = await api_client.get_user(member['user_id'])
            
            if not user_result.get('success') or not user_result.get('data'):
                # User not registered, register them
                user_data = {
                    'user_id': member['user_id'],
                    'username': member['username'],
                    'first_name': member['first_name'],
                    'last_name': member['last_name'],
                    'language_code': member['language_code'],
                    'is_premium': member['is_premium'],
                    'is_bot': False,
                    'user_agent': '',
                    'ip_address': '',
                    'quick_mode': False,
                    'download_quality': '192',
                    'show_artwork': True,
                    'auto_download': False,
                    'notifications': True
                }
                
                result = await api_client.register_user(user_data)
                if result.get('success'):
                    registered_count += 1
                    # Load default settings for new user
                    set_default_user_settings(member['user_id'])
                else:
                    failed_count += 1
            else:
                # User exists, load their settings
                await load_user_settings(member['user_id'])
                
        except Exception as e:
            logger.error(f"Failed to register user {member['user_id']}: {e}")
            failed_count += 1
        
        await asyncio.sleep(0.1)  # Small delay to avoid rate limiting
    
    logger.info(f"Auto-registration completed: {registered_count} registered, {failed_count} failed, {len(members)} total members")


async def register_single_user_from_channel(user_id: int):
    """Register a single user when they join the channel (optional webhook)"""
    if not INFO_CHANNEL_ID:
        return False
    
    try:
        chat_member = await bot.get_chat_member(INFO_CHANNEL_ID, user_id)
        if chat_member and not chat_member.user.is_bot:
            user = chat_member.user
            user_data = {
                'user_id': user.id,
                'username': user.username or '',
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'language_code': getattr(user, 'language_code', 'en'),
                'is_premium': getattr(user, 'is_premium', False),
                'is_bot': False,
                'user_agent': '',
                'ip_address': '',
                'quick_mode': False,
                'download_quality': '192',
                'show_artwork': True,
                'auto_download': False,
                'notifications': True
            }
            
            result = await api_client.register_user(user_data)
            if result.get('success'):
                set_default_user_settings(user.id)
                logger.info(f"Auto-registered new channel member: {user.id}")
                return True
    except Exception as e:
        logger.error(f"Failed to register user {user_id} from channel: {e}")
    
    return False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    logger.info(f'"{BOT_NAME}" در حال راه‌اندازی...')
    while True:
        try:
            bot.run()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.exception(f"ربات crashed: {e}")
            time.sleep(60)