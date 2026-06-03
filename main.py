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
from crawlers.itunes import search_itunes, lookup_itunes, fetch_itunes, set_mirror, get_mirror
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

# Store user preferences
user_download_quality = {}  # user_id -> DownloadQuality
user_show_artwork = {}  # user_id -> bool (default True)
user_quick_mode = {}  # user_id -> bool (default False)
user_auto_download = {}  # user_id -> bool (default False) - Auto download on search
user_notifications = {}  # user_id -> bool (default True) - Receive notifications

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
            logger.info("Upload error notification already active, skipping duplicate notification")
            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")
            return
        
        if current_time - self.last_error_time < self.error_cooldown:
            logger.info(f"Upload error notification on cooldown, skipping (last error: {self.last_error_time})")
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
            logger.warning(f"Bale upload error notification sent to channel {INFO_CHANNEL_ID}")
            
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
    logger.info(f"Upload error flag set for user {user_id}, collection {collection_id}")
    album_tracker.cancel_download(user_id, collection_id)
    logger.info(f"Album download cancelled for user {user_id}, collection {collection_id} due to upload error")


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
        logger.error(f"Failed to check membership for user {user_id} in channel {channel_id}: {e}")
        return False


async def verify_all_memberships(user_id: int) -> tuple[bool, List[Dict]]:
    result = await api_client.get_required_channels()
    if not result.get('success'):
        logger.error("Failed to get required channels from API")
        return True, []

    channels = result.get('data', [])
    missing_channels = []

    for channel in channels:
        channel_id = channel.get('channel_id')
        if not await check_channel_membership(user_id, channel_id):
            missing_channels.append(channel)

    return len(missing_channels) == 0, missing_channels


async def require_membership(func):
    async def wrapper(message, *args, **kwargs):
        user_id = message.author.id
        chat_id = message.chat.id
        is_group = message.chat.type in ["group", "supergroup"]

        if is_group or str(message.content or "").startswith("/start"):
            return await func(message, *args, **kwargs)

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

            await reply_message(
                message,
                f"⚠️ *برای استفاده از ربات باید در کانال‌های زیر عضو شوید:*\n\n"
                f"{channels_text}\n\n"
                f"پس از عضویت، دوباره تلاش کنید."
            )
            return None

        return await func(message, *args, **kwargs)
    return wrapper


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
    
    async def get_user_settings(self, user_id: int) -> Dict:
        return await self._request('get_user_settings', {'user_id': user_id})

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
# HTTP Session & Semaphores
# ============================================================================
HTTP_SESSION: Optional[aiohttp.ClientSession] = None
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(20)

MESSAGE_OWNER = {}
MESSAGE_OWNER_TTL = 600

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

SEARCH_CACHE_TTL = 600
ARTWORK_CACHE_TTL = 86400
PREVIEW_CACHE_TTL = 86400
TRACK_CACHE_TTL = 604800

USER_SESSIONS = {}


def get_cache_file_path(cache_key: str) -> Path:
    safe_name = hashlib.md5(cache_key.encode()).hexdigest()
    return CACHE_DIR / f"{safe_name}.cache"


async def save_to_file_cache(cache_key: str, data: Any, ttl: int = SEARCH_CACHE_TTL):
    try:
        cache_path = get_cache_file_path(cache_key)
        cache_data = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl
        }
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_data, f)
        return True
    except Exception as e:
        logger.error(f"Failed to save to file cache {cache_key}: {e}")
        return False


async def get_from_file_cache(cache_key: str) -> Optional[Any]:
    try:
        cache_path = get_cache_file_path(cache_key)
        if not cache_path.exists():
            return None

        with open(cache_path, 'rb') as f:
            cache_data = pickle.load(f)

        if time.time() - cache_data["timestamp"] > cache_data["ttl"]:
            cache_path.unlink(missing_ok=True)
            return None

        return cache_data["data"]
    except Exception as e:
        logger.error(f"Failed to read from file cache {cache_key}: {e}")
        return None


async def clear_expired_cache():
    while True:
        await asyncio.sleep(3600)
        try:
            now = time.time()
            for cache_file in CACHE_DIR.glob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                    if now - cache_data["timestamp"] > cache_data["ttl"]:
                        cache_file.unlink()
                except:
                    cache_file.unlink()
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")


SEARCH_CACHE = {}
SEARCH_CACHE_MAX_ITEMS = 100


async def cleanup_caches():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        expired = [sid for sid, data in SEARCH_CACHE.items() if now - data["timestamp"] > SEARCH_CACHE_TTL]
        for sid in expired:
            SEARCH_CACHE.pop(sid, None)
        expired_msgs = [mid for mid, (_, ts) in MESSAGE_OWNER.items() if now - ts > MESSAGE_OWNER_TTL]
        for mid in expired_msgs:
            MESSAGE_OWNER.pop(mid, None)


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
    def __init__(self, max_downloads: int = 80, time_window: int = 7200):
        self.max_downloads = max_downloads
        self.time_window = time_window
        self.users: Dict[int, List[float]] = defaultdict(list)

    async def can_download(self, user_id: int) -> tuple[bool, int]:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]
        if len(self.users[user_id]) >= self.max_downloads:
            oldest = min(self.users[user_id])
            wait_seconds = int(self.time_window - (now - oldest))
            return False, wait_seconds
        return True, 0

    def record_download(self, user_id: int):
        now = time.time()
        self.users[user_id].append(now)

    def get_remaining(self, user_id: int) -> int:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]
        return max(0, self.max_downloads - len(self.users[user_id]))


download_rate_limiter = DownloadRateLimiter(max_downloads=100, time_window=3600)

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


user_states = {}
user_last_message = {}


# ============================================================================
# User Registration
# ============================================================================
async def register_user(message: Message):
    user = message.author
    user_data = {
        'user_id': user.id,
        'username': user.username or '',
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'language_code': getattr(user, 'language_code', 'en'),
        'is_premium': getattr(user, 'is_premium', False),
        'is_bot': getattr(user, 'is_bot', False),
        'user_agent': message.content or '',
        'ip_address': ''
    }

    result = await api_client.register_user(user_data)
    if result.get('success'):
        logger.info(f"User {user.id} registered successfully")
        settings_result = await api_client.get_user_settings(user.id)
        if settings_result.get('success'):
            settings = settings_result.get('data', {})
            user_quick_mode[user.id] = settings.get('quick_mode', False)
            user_show_artwork[user.id] = settings.get('show_artwork', True)
            user_auto_download[user.id] = settings.get('auto_download', False)
            user_notifications[user.id] = settings.get('notifications', True)
            quality_str = settings.get('download_quality', '192')
            try:
                user_download_quality[user.id] = DownloadQuality(quality_str)
            except ValueError:
                user_download_quality[user.id] = DownloadQuality.MEDIUM
    else:
        logger.error(f"Failed to register user {user.id}: {result.get('message')}")
        user_quick_mode[user.id] = False
        user_download_quality[user.id] = DownloadQuality.MEDIUM
        user_show_artwork[user.id] = True
        user_auto_download[user.id] = False
        user_notifications[user.id] = True


# ============================================================================
# Broadcasting System
# ============================================================================
async def process_broadcast_message(message: Message):
    chat_id = str(message.chat.id)
    chat = await bot.get_chat(int(chat_id))

    result = await api_client.get_broadcast_channels()
    if not result.get('success'):
        return

    broadcast_channels = result.get('data', [])
    channel_config = None

    for channel in broadcast_channels:
        if channel.get('channel_id') == chat_id:
            channel_config = channel
            break

    if not channel_config:
        return

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

    users_result = await api_client.get_active_users()
    if not users_result.get('success'):
        logger.error("Failed to get active users for broadcast")
        return

    users = users_result.get('data', [])
    successful = 0
    failed = 0

    for user in users:
        user_id = user['id']
        # Skip users who disabled notifications
        if not user_notifications.get(user_id, True):
            continue
        try:
            await bot.forward_message(chat_id=user_id, message_id=message.id, from_chat_id=message.chat.id)
            successful += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user['id']}: {e}")
            failed += 1

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
# Album Download Tracker
# ============================================================================
@dataclass
class TrackDownloadStatus:
    name: str
    success: bool = False
    error: str = None
    order: int = 0


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
            "collection_name": collection_name,
            "start_time": time.time(),
            "lock_acquired": True,
            "cover_bytes": None
        }

    def add_track(self, user_id: int, collection_id: int, track_name: str, order: int):
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return
        self.active_downloads[key]["tracks"].append(TrackDownloadStatus(name=track_name, order=order))

    def set_cover_bytes(self, user_id: int, collection_id: int, cover_bytes: bytes):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key]["cover_bytes"] = cover_bytes

    def get_cover_bytes(self, user_id: int, collection_id: int) -> Optional[bytes]:
        key = (user_id, collection_id)
        if key in self.active_downloads:
            return self.active_downloads[key].get("cover_bytes")
        return None

    def update_track_result(self, user_id: int, collection_id: int, track_name: str, success: bool, error_msg: str = None):
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return
        tracker = self.active_downloads[key]
        for track in tracker["tracks"]:
            if track.name == track_name:
                track.success = success
                track.error = error_msg
                break
        tracker["current_idx"] += 1

    def get_progress_text(self, user_id: int, collection_id: int) -> str:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return ""
        t = self.active_downloads[key]
        completed = sum(1 for tr in t["tracks"] if tr.success)
        failed = sum(1 for tr in t["tracks"] if not tr.success and tr.error is not None)
        elapsed = time.time() - t["start_time"]

        if t["current_idx"] > 0:
            avg_time = elapsed / t["current_idx"]
            remaining = avg_time * (t["total"] - t["current_idx"])
            eta = f"⏱️ زمان تقریبی باقیمانده: {int(remaining)} ثانیه"
        else:
            eta = ""

        text = f"📀 *دانلود آلبوم: {t['collection_name']}*\n"
        if t["current_idx"] < t["total"] and t["tracks"] and t["current_idx"] < len(t["tracks"]):
            current_track = t["tracks"][t["current_idx"]]
            text += f"🎵 *در حال دانلود:* {current_track.name} ({t['current_idx'] + 1}/{t['total']})\n"
        text += f"✅ موفق: {completed}\n❌ ناموفق: {failed}\n"
        if eta:
            text += f"{eta}\n"
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
            logger.info(f"Album download cancelled for key {key}")


album_tracker = AlbumDownloadTracker()


# ============================================================================
# Search and Download Functions
# ============================================================================
async def quick_search_and_send(bot: Client, chat_id: int, user_id: int, term: str, original_message: Message = None):
    status_msg = await send_message(bot, chat_id, f"⚡ *حالت سریع: جستجوی {term}...*")

    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)

        if results and results.get("resultCount", 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            if track_id:
                if user_auto_download.get(user_id, False):
                    asyncio.create_task(download_and_send_single_track(bot, chat_id, track_id, user_id))
                    await status_msg.delete()
                else:
                    await show_track_page(chat_id, track_id, original_message, user_id)
                    await status_msg.delete()
                await api_client.log_search(user_id, 'quick', term, 1)
            else:
                await send_error_with_retry(bot, chat_id, f"نتیجه‌ای برای '{term}' یافت نشد.",
                                            f"quick_retry:{term}", status_msg)
        else:
            await send_error_with_retry(bot, chat_id, f"نتیجه‌ای برای '{term}' یافت نشد.",
                                        f"quick_retry:{term}", status_msg)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در جستجو: {str(e)[:100]}",
                                    f"quick_retry:{term}", status_msg)


async def send_audio_with_retry(bot: Client, chat_id: int, audio_path: str, file_name: str, caption: str,
                                max_retries=2, direct=False, track_id=None, user_id=None, collection_id=None):
    last_exception = None
    abs_audio_path = os.path.abspath(str(audio_path))

    exists = await asyncio.to_thread(os.path.exists, abs_audio_path)
    if not exists:
        logger.error(f"File not found for upload: {abs_audio_path}")
        raise FileNotFoundError(f"File not found: {abs_audio_path}")

    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_audio_path, 'rb') as audio_file:
                logger.info(f'Sending audio, attempt {attempt}/{max_retries}...')
                markup = [[InlineKeyboardButton(
                    text="📂 نمایش در مینی اپ",
                    web_app="https://player.abraava.ir?id=" + track_id
                )], [InlineKeyboardButton(
                    text="📋 کپی پیوند",
                    copy_text="https://player.abraava.ir?id=" + track_id
                )]]
                msg = await send_audio(bot, chat_id=chat_id, audio=audio_file, caption=caption, reply_markup=markup)
                await set_mirror('track', str(track_id), 'audioUrl',
                                 'https://tapi.bale.ai/file/bot<token>/' + str(msg.audio.id))
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
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                raise Exception("آپلود در بله به مشکل مواجه شد. لطفاً بعداً تلاش کنید یا آهنگ دیگری انتخاب کنید.")

    raise last_exception if last_exception else Exception("آپلود در بله به مشکل مواجه شد")


async def download_and_send_single_track(bot: Client, chat_id: int, track_id: int, user_id: int = None,
                                         status_msg: Message = None, is_batch: bool = False, 
                                         album_cover_bytes: bytes = None, collection_id: int = None):
    if is_batch or status_msg is None:
        status_msg = await send_message(bot, chat_id, text=f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*")

    track_data = await get_track(track_id, status_msg if True else None)
    if not track_data or not track_data.get("results"):
        await send_error_with_retry(bot, chat_id, "خطا در دریافت اطلاعات آهنگ.",
                                    f"download_retry:{track_id}", status_msg)
        return

    track = track_data["results"][0]
    release_year = track.get("releaseDate", "").split("-")[0] if track.get("releaseDate") else ""

    quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    quality_value = quality.value
    
    caption_parts = [
        f"🎵 آهنگ: {track.get('trackName', 'Unknown Title')}",
        f"🎤 هنرمند: {track.get('artistName', 'Unknown Artist')}",
        f"📀 کیفیت: {quality_value}kbps",
    ]
    if track.get('collectionName'):
        caption_parts.append(f"📀 آلبوم: {track.get('collectionName')}")
    if release_year:
        caption_parts.append(f"📅 انتشار: {release_year}")
    if track.get('primaryGenreName'):
        caption_parts.append(f"🎸 سبک: {track.get('primaryGenreName')}")
    if track.get('trackExplicitness') == 'explicit':
        caption_parts.append(f"🔞 Explicit")
    if track.get('trackTimeMillis'):
        duration_sec = int(track['trackTimeMillis']) // 1000
        minutes = duration_sec // 60
        seconds = duration_sec % 60
        caption_parts.append(f"⏱️ مدت زمان: {minutes}:{seconds:02d}")

    caption = "\n".join(caption_parts)
    markup = [[InlineKeyboardButton(
        text="📂 نمایش در مینی اپ",
        web_app="https://player.abraava.ir?id=" + str(track_id)
    )], [InlineKeyboardButton(
        text="📋 کپی پیوند",
        copy_text="https://player.abraava.ir?id=" + str(track_id)
    )]]

    audio_cache = None
    if track_id:
        data = await get_mirror('track', str(track_id), 'audioUrl')
        if data.get("mirrors", {}).get('audioUrl', False):
            audio_cache = data["mirrors"]['audioUrl']['url'].split('<token>/')[1]

    if audio_cache:
        try:
            await update_status_with_close(status_msg, f"📤 *در حال ارسال فایل از حافظه کش...*")
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
        await send_error_with_retry(bot, chat_id, "آهنگ در دیتابیس محلی یافت نشد و بات در حالت آفلاین است.",
                                    f"download_retry:{track_id}", status_msg)
        return

    t_name = track.get("trackName", "Unknown Title")
    ye = track.get("releaseDate", "").split("-")[0]
    a_name = track.get("artistName", "Unknown Artist")
    collection_name = track.get("collectionName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100", track.get("artworkUrl")), size=600)

    await update_status_with_close(status_msg, f"🔍 *جستجوی سورس باکیفیت آهنگ در یوتیوب موزیک...*")

    try:
        video_id = await search_youtube_track(t_name, a_name, collection_name, ye)
        if not video_id:
            await send_error_with_retry(bot, chat_id, "نتوانستیم لینک یوتیوب موزیک را برای این آهنگ پیدا کنیم.",
                                        f"download_retry:{track_id}", status_msg)
            return

        video_url = f"https://music.youtube.com/watch?v={video_id}"
        await update_status_with_close(status_msg, f"⏳ *در صف دانلود و آماده‌سازی...*")

        mp3_path_str = None
        temp_dir_to_clean = None
        try:
            async with DOWNLOAD_SEMAPHORE:
                await update_status_with_close(status_msg, f"⏳ *در حال دانلود و پردازش با کیفیت {quality_value}kbps...*")
                mp3_path_str = await download_audio(video_url, quality=quality_value)
                temp_dir_to_clean = os.path.dirname(mp3_path_str)

                if not mp3_path_str or not os.path.exists(mp3_path_str):
                    await send_error_with_retry(bot, chat_id, "دانلود با شکست مواجه شد — همه روش‌ها ناموفق بودند.",
                                                f"download_retry:{track_id}", status_msg)
                    return

                file_size_mb = os.path.getsize(mp3_path_str) / (1024 * 1024)
                if file_size_mb == 0:
                    await send_error_with_retry(bot, chat_id, "خطای داخلی: فایل دانلود شده یافت نشد.",
                                                f"download_retry:{track_id}", status_msg)
                    return

                cover_bytes = album_cover_bytes
                show_artwork = user_show_artwork.get(user_id, True)
                
                if show_artwork and cover_bytes is None and cover_url and HTTP_SESSION:
                    try:
                        await update_status_with_close(status_msg, f"🖼️ *در حال دریافت کاور آلبوم...*")
                        async with HTTP_SESSION.get(cover_url) as resp:
                            if resp.status == 200:
                                cover_bytes = await resp.read()
                    except Exception as e:
                        logger.error(f"Failed to download cover: {e}")

                await asyncio.get_event_loop().run_in_executor(None, tag_mp3, mp3_path_str, track, cover_bytes)
                await update_status_with_close(status_msg, f"☁️ *در حال آپلود در سرورهای ابری {BOT_NAME}...*")

                try:
                    await send_audio_with_retry(bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption, 
                                                track_id=str(track['trackId']), user_id=user_id, collection_id=collection_id)
                    await bale_error_notifier.check_and_clear_if_resolved(bot, test_success=True)
                except Exception as upload_error:
                    logger.error(f"Upload failed: {str(upload_error)}")
                    raise

                await api_client.log_download(
                    user_id=user_id, track_id=str(track_id), track_name=t_name, artist_name=a_name,
                    album_name=collection_name, file_size=int(file_size_mb * 1024 * 1024),
                    download_source='youtube', quality=quality_value
                )
                download_rate_limiter.record_download(user_id)
                
                try:
                    await status_msg.delete()
                except:
                    pass

        except Exception as e:
            logger.exception("Download error")
            await send_error_with_retry(bot, chat_id, f"خطا در عملیات: {str(e)[:100]}",
                                        f"download_retry:{track_id}", status_msg)
        finally:
            if temp_dir_to_clean and os.path.exists(temp_dir_to_clean):
                try:
                    import shutil
                    shutil.rmtree(temp_dir_to_clean, ignore_errors=True)
                except:
                    pass

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در جستجوی یوتیوب: {str(e)[:100]}",
                                    f"download_retry:{track_id}", status_msg)


async def send_voice_preview(bot: Client, chat_id: int, track_id: int, user_id: int = None):
    status_msg = await send_message(bot, chat_id, f"⏳ *در حال دریافت پیش‌نمایش...*")

    try:
        track_data = await get_track(track_id)
        if not track_data or not track_data.get("results"):
            await send_error_with_retry(bot, chat_id, f"اطلاعات آهنگ یافت نشد.",
                                        f"preview_retry:{track_id}", status_msg)
            return

        track = track_data["results"][0]
        preview_url = track.get("previewUrl")

        if not preview_url:
            await send_error_with_retry(bot, chat_id, f"متاسفانه پیش‌نمایشی برای این آهنگ موجود نیست.",
                                        f"preview_retry:{track_id}", status_msg)
            return

        cache_id = track['trackId']
        preview_cache = None
        if cache_id:
            data = await get_mirror('track', cache_id, 'previewUrl')
            if data.get("mirrors", {}).get('previewUrl', False):
                preview_cache = data["mirrors"]['previewUrl']['url'].split('<token>/')[1]
                preview_url = preview_cache

        msg = await send_voice(bot, chat_id, voice=preview_url,
                               caption=f"🎧 *پیش‌نمایش صوتی آهنگ {track.get('trackName')}*")
        if msg and not preview_cache:
            await set_mirror('track', str(track_id), 'previewUrl',
                             'https://tapi.bale.ai/file/bot<token>/' + str(msg.voice.id))
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Failed to send audio preview: {e}")
        await send_error_with_retry(bot, chat_id, f"خطا در ارسال پیش‌نمایش: {str(e)[:100]}",
                                    f"preview_retry:{track_id}", status_msg)


async def download_and_send_album(bot: Client, chat_id: int, collection_id: int, user_id: int,
                                  collection_name: str, tracks: List[dict], status_msg: Message):
    if not await album_tracker.acquire_lock(user_id, collection_id):
        await update_status_with_close(status_msg,
                                       "❌ *در حال حاضر دانلود این آلبوم در حال انجام است*\nلطفاً چند لحظه صبر کنید.")
        album_tracker.finish_download(user_id, collection_id, 0, 0)
        release_user_download_lock(user_id)
        return

    album_tracker.start_download(user_id, collection_id, status_msg, len(tracks), collection_name)

    for idx, track in enumerate(tracks, 1):
        album_tracker.add_track(user_id, collection_id, track.get('trackName', 'Unknown'), idx)

    cancel_markup = [
        [InlineKeyboardButton(text="❌ لغو دانلود آلبوم", callback_data=f"cancel_album:{user_id}:{collection_id}")],
    ]
    await update_status_with_close(status_msg, album_tracker.get_progress_text(user_id, collection_id),
                                   reply_markup=cancel_markup, no=True)

    album_cover_bytes = None
    show_artwork = user_show_artwork.get(user_id, True)
    
    if show_artwork and tracks and len(tracks) > 0:
        first_track = tracks[0]
        cover_url = get_high_res_artwork(first_track.get("artworkUrl100", first_track.get("artworkUrl")), size=600)
        if cover_url and HTTP_SESSION:
            try:
                async with HTTP_SESSION.get(cover_url) as resp:
                    if resp.status == 200:
                        album_cover_bytes = await resp.read()
                        album_tracker.set_cover_bytes(user_id, collection_id, album_cover_bytes)
                        logger.info(f"Album cover art downloaded once for {collection_name}")
            except Exception as e:
                logger.error(f"Failed to download album cover: {e}")

    success_count = 0
    failed_tracks = []
    stopped_by_rate_limit = False
    stopped_by_upload_error = False

    for idx, track in enumerate(tracks, 1):
        key = (user_id, collection_id)
        if album_upload_error_flag.get(key, False):
            logger.info(f"Upload error detected, stopping album download for {collection_name}")
            stopped_by_upload_error = True
            album_tracker.cancel_download(user_id, collection_id)
            album_upload_error_flag.pop(key, None)
            break
        
        if album_tracker.is_cancelled(user_id, collection_id):
            await update_status_with_close(status_msg,
                                           f"⏹️ *دانلود آلبوم لغو شد*\n{album_tracker.get_progress_text(user_id, collection_id)}")
            album_tracker.finish_download(user_id, collection_id, success_count, len(failed_tracks))
            release_user_download_lock(user_id)
            return

        track_id = track.get('trackId')
        track_name = track.get('trackName', 'Unknown')

        can_dl, wait_sec = await download_rate_limiter.can_download(user_id)
        if not can_dl:
            stopped_by_rate_limit = True
            error_msg = f"محدودیت دانلود: {wait_sec} ثانیه تا مجوز بعدی صبر کنید"
            album_tracker.update_track_result(user_id, collection_id, track_name, False, error_msg)
            failed_tracks.append({"name": track_name, "error": error_msg})
            break

        try:
            await download_and_send_single_track(bot, chat_id, track_id, user_id, status_msg, 
                                                 is_batch=True, album_cover_bytes=album_cover_bytes, 
                                                 collection_id=collection_id)
            download_rate_limiter.record_download(user_id)
            album_tracker.update_track_result(user_id, collection_id, track_name, True)
            success_count += 1
        except Exception as e:
            error_msg = str(e)[:100]
            logger.error(f"Failed to download track {track_name}: {error_msg}")
            album_tracker.update_track_result(user_id, collection_id, track_name, False, error_msg)
            failed_tracks.append({"name": track_name, "error": error_msg})
            
            if "آپلود" in error_msg or "upload" in error_msg.lower() or "بله" in error_msg:
                logger.info(f"Upload error detected in track {track_name}, stopping album download")
                album_tracker.cancel_download(user_id, collection_id)
                stopped_by_upload_error = True
                break

        await update_status_with_close(status_msg, album_tracker.get_progress_text(user_id, collection_id),
                                       reply_markup=cancel_markup, no=True)
        await asyncio.sleep(2)
    
    key = (user_id, collection_id)
    if album_upload_error_flag.get(key, False):
        stopped_by_upload_error = True
        album_upload_error_flag.pop(key, None)

    final_text = f"✅ *دانلود آلبوم {collection_name} به پایان رسید*\n\n"
    final_text += f"📊 جمع کل: {len(tracks)} قطعه\n"
    final_text += f"✅ موفق: {success_count}\n"
    if failed_tracks:
        final_text += f"❌ ناموفق: {len(failed_tracks)}\n\n"
        final_text += "⚠️ *قطعات ناموفق:*\n"
        for ft in failed_tracks[:10]:
            final_text += f"- {ft['name']}\n"
        if len(failed_tracks) > 10:
            final_text += f"... و {len(failed_tracks) - 10} قطعه دیگر\n"
    if stopped_by_rate_limit:
        final_text += "\n🚫 *توقف به دلیل محدودیت ۱۰۰ دانلود در ساعت.*"
    if stopped_by_upload_error:
        final_text += "\n⚠️ *توقف دانلود آلبوم به دلیل اختلال در سرویس آپلود بله.*"

    await edit_or_send(bot, chat_id, status_msg, final_text, owner_id=user_id)
    album_tracker.finish_download(user_id, collection_id, success_count, len(failed_tracks))
    release_user_download_lock(user_id)


# ============================================================================
# Display Functions
# ============================================================================
async def show_artist_page(chat_id: int, artist_id: int, page: int = 1,
                           message_to_edit: Optional[Message] = None, owner_id: int = None, force=False):
    status_msg = await send_message(bot, chat_id, f"🔄 *در حال پردازش هنرمند...*")

    try:
        artist_data = await get_or_crawl_artist(artist_id=artist_id, status_msg=status_msg, force=force)
        if not artist_data:
            await send_error_with_retry(bot, chat_id, f"هنرمند یافت نشد.",
                                        f"artist_retry:{artist_id}", status_msg)
            return
        artist_data = artist_data['results'][0]
        artist_image = get_artist_image(artist_data.get('artistName'))

        text = f"*🎤 هنرمند:* {artist_data.get('artistName', 'نامشخص')}\n"
        text += f"*🎭 سبک:* {artist_data.get('primaryGenreName', 'نامشخص')}\n"
        if artist_data.get("artistLinkUrl"):
            text += f"*🔗 لینک آیتونز:* [مشاهده در آیتونز]({artist_data['artistLinkUrl']})\n"

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

            text += f"\n*📀 آلبوم‌ها ({total_items}):*\n"
            for collection in page_items:
                if collection['wrapperType'] == 'collection':
                    btn_text = f"📀 {collection.get('collectionName', 'نامشخص')[:45]}"
                    markup.append([InlineKeyboardButton(
                        text=btn_text,
                        callback_data=f"collection:{collection['collectionId']}:1"
                    )])

            if total_pages > 1:
                pagination_row = create_pagination_row(f"artist:{artist_id}", page, total_pages)
                markup.append(pagination_row)
        markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup,
                           owner_id=owner_id, artwork_url=artist_image, artist_id=artist_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش هنرمند: {str(e)[:100]}",
                                    f"artist_retry:{artist_id}", status_msg)


async def show_collection_page(chat_id: int, collection_id: int, page: int = 1,
                               message_to_edit: Optional[Message] = None, owner_id: int = None, force=False):
    status_msg = await send_message(bot, chat_id, f"🔄 *در حال پردازش آلبوم...*")
    try:
        collection_data = await get_or_crawl_collection(collection_id, status_msg, force)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)
        tracks = tracks_data["results"] if tracks_data else []
        if not collection_data:
            await send_error_with_retry(bot, chat_id, f"آلبوم یافت نشد.",
                                        f"collection_retry:{collection_id}", status_msg)
            return
        collection_data = collection_data['results'][0]
        release_date = collection_data.get('releaseDate', 'نامشخص')[:10] if collection_data.get(
            'releaseDate') else 'نامشخص'
        text = f"*📀 آلبوم:* {collection_data.get('collectionName', 'نامشخص')}\n"
        text += f"*🎤 هنرمند:* {collection_data.get('artistName', 'نامشخص')}\n"
        text += f"*📅 انتشار:* {release_date}\n"
        text += f"*🎭 سبک:* {collection_data.get('primaryGenreName', 'نامشخص')}\n"
        if collection_data.get("collectionViewUrl"):
            text += f"*🔗 لینک آیتونز:* [مشاهده در آیتونز]({collection_data['collectionViewUrl']})\n"

        markup = []
        if tracks:
            total_items = len(tracks)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_items = tracks[start_idx:end_idx]

            text += f"\n*🎵 قطعات ({total_items}):*\n"
            for i, track in enumerate(page_items, start_idx + 1):
                track_time = track.get('trackTimeMillis', 0)
                track_time = int(track_time)
                if isinstance(track_time, str):
                    track_time = int(track_time) if track_time.isdigit() else 0
                duration = format_duration(track_time)
                text += f"{i}. {track.get('trackName', 'نامشخص')} ({duration})\n"

            for track in page_items:
                if track['wrapperType'] == 'track':
                    markup.append([InlineKeyboardButton(
                        text=f"🎵 {track.get('trackName', 'نامشخص')[:40]} - {track.get('artistName', 'نامشخص')[:40]}",
                        callback_data=f"track:{track['trackId']}"
                    )])

            if total_pages > 1:
                pagination_row = create_pagination_row(f"collection:{collection_id}", page, total_pages)
                markup.append(pagination_row)

            chat = await bot.get_chat(chat_id)
            if chat.type != "group" and chat.type != "supergroup":
                if tracks and len(tracks) > 0:
                    markup.append([InlineKeyboardButton(
                        text="⬇️ دانلود کل آلبوم",
                        callback_data=f"download_album:{collection_id}"
                    )])

        if collection_data.get("artistId"):
            markup.append([InlineKeyboardButton(
                text="🎤 مشاهده هنرمند",
                callback_data=f"artist:{collection_data['artistId']}:1"
            )])
        markup.append(
            [InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:collection:{collection_id}")])
        artwork_url = get_high_res_artwork(collection_data.get("artworkUrl100"))
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup,
                           artwork_url=artwork_url, cache_id=collection_id, owner_id=owner_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش آلبوم: {str(e)[:100]}",
                                    f"collection_retry:{collection_id}", status_msg)


async def show_track_page(chat_id: int, track_id: int, message_to_edit: Optional[Message] = None, owner_id: int = None):
    status_msg = await send_message(bot, chat_id, f"🔄 *در حال بارگذاری اطلاعات آهنگ...*")

    try:
        data = await get_track(track_id, status_msg)
        if not data or not data.get("results"):
            await send_error_with_retry(bot, chat_id, f"آهنگ یافت نشد.",
                                        f"track_retry:{track_id}", status_msg)
            return
        track = data["results"][0]
        duration = format_duration(track.get('trackTimeMillis', 0))
        release_date = track.get('releaseDate', 'نامشخص')[:10] if track.get('releaseDate') else 'نامشخص'
        text = f"*🎵 آهنگ:* {track.get('trackName', 'نامشخص')}\n"
        text += f"*🎤 هنرمند:* {track.get('artistName', 'نامشخص')}\n"
        text += f"*📀 آلبوم:* {track.get('collectionName', 'نامشخص')}\n"
        text += f"*⏱️ مدت زمان:* {duration}\n"
        text += f"*🎭 سبک:* {track.get('primaryGenreName', 'نامشخص')}\n"
        text += f"*📅 انتشار:* {release_date}\n"
        if track.get("trackViewUrl"):
            text += f"*🔗 لینک آیتونز:* [مشاهده در آیتونز]({track['trackViewUrl']})\n"

        markup = []
        download = [InlineKeyboardButton(text="⬇️ دانلود", callback_data=f"download:{track_id}")]
        if track.get("previewUrl"):
            download.append(InlineKeyboardButton(text="🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"))
        markup.append(download)
        links = []
        if track.get('collectionId'):
            links.append(
                InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"collection:{track['collectionId']}:1"))
        if track.get('artistId'):
            links.append(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"))
        markup.append(links)
        artwork_url = get_high_res_artwork(track.get("artworkUrl", track.get("artworkUrl100")))
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup, artwork_url=artwork_url,
                           cache_id=track.get('collectionId'), owner_id=owner_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش آهنگ: {str(e)[:100]}",
                                    f"track_retry:{track_id}", status_msg)


async def handle_search_command(chat_id: int, user_id: int, type_: str, term: str, original_message: Message = None,
                                owner_id: int = None):
    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "quick": "سریع"}

    status_msg = await send_message(bot, chat_id,
                                    f"🔍 *در حال جستجوی {type_fa_map.get(type_)}: {term}...*")

    try:
        results = {}
        if not OFFLINE_MODE:
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            entity = entity_map.get(type_) if type_ != "all" else None
            itunes_results = await search_itunes(term, entity=entity, limit=50)
            if itunes_results and itunes_results.get("resultCount", 0) > 0:
                results = itunes_results

        if results and results.get("resultCount", 0) > 0:
            await send_search_page(chat_id, type_, term, results, 1, original_term=term, owner_id=owner_id or user_id)
            await status_msg.delete()
            await api_client.log_search(user_id, type_, term, results.get("resultCount", 0))
        else:
            await send_error_with_retry(bot, chat_id, f"هیچ نتیجه‌ای برای '{term}' یافت نشد.",
                                        f"search_retry:{type_}:{term}", status_msg)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در جستجو: {str(e)[:100]}",
                                    f"search_retry:{type_}:{term}", status_msg)


async def send_search_page(chat_id: int, type_: str, term: str, results: dict, page: int,
                           message_to_edit: Optional[Message] = None,
                           original_term: Optional[str] = None,
                           owner_id: int = None):
    results_list = results["results"]
    total_items = len(results_list)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = results_list[start_idx:end_idx]
    type_fa_map = {"artist": "هنرمند", "collection": "آلبوم", "track": "آهنگ", "all": "همه"}
    markup = []

    if type_ == "all":
        header = f"📋 *نتایج جستجوی ترکیبی برای: {term}*\nتعداد کل: {total_items} مورد"
    else:
        header = f"📋 *نتایج جستجو برای {type_fa_map.get(type_, type_)}: {term}*\nتعداد کل: {total_items} مورد"

    for item in page_items:
        wrapper = item.get("wrapperType")
        if wrapper == "artist":
            btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
            callback = f"artist:{item['artistId']}:1"
        elif wrapper == "collection":
            btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
            callback = f"collection:{item['collectionId']}:1"
        elif wrapper == "track":
            btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
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

    text = header
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=markup, owner_id=owner_id)


async def edit_or_send(bot: Client, chat_id: int, message_to_edit: Optional[Message], text: str,
                       markup=None, artwork_url: str = None, cache_id=None, owner_id=None, artist_id=None):
    if markup is None:
        markup = []

    msg = None
    show_artwork = user_show_artwork.get(owner_id, True) if owner_id else True
    
    if artwork_url and show_artwork:
        artwork_cache = None
        entity_type = "collection"
        if artist_id:
            entity_type = "artist"
            cache_id = artist_id

        if cache_id:
            data = await get_mirror(entity_type, cache_id, 'artworkUrl')
            if data.get("mirrors", {}).get('artworkUrl', False):
                artwork_cache = data["mirrors"]['artworkUrl']['url'].split('<token>/')[1]

        try:
            photo_to_send = artwork_url
            if artwork_cache:
                photo_to_send = artwork_cache

            if photo_to_send:
                msg = await send_photo(bot, chat_id, photo=photo_to_send, caption=text, reply_markup=markup)
            else:
                msg = await send_message(bot, chat_id, text=text, reply_markup=markup)

            if cache_id and not artwork_cache and msg and photo_to_send:
                await set_mirror(entity_type, cache_id, 'artworkUrl',
                                 'https://tapi.bale.ai/file/bot<token>/' + str(msg.photo[0].id))

        except Exception as e:
            logger.error(f"Failed to send photo: {e}")
            msg = await send_message(bot, chat_id, text=text, reply_markup=markup, no=True)
    else:
        msg = await send_message(bot, chat_id, text, reply_markup=markup)

    if owner_id and msg and msg.chat.type in ["group", "supergroup"]:
        set_message_owner(msg.id, owner_id)

    if message_to_edit and message_to_edit != msg:
        try:
            if message_to_edit.id in MESSAGE_OWNER:
                MESSAGE_OWNER.pop(message_to_edit.id, None)
            if not "نتایج جستجو" in str(message_to_edit.content or ""):
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


async def show_user_stats(user_id: int, chat_id: int, message_id: int = None):
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

    stats_text = (
        f"📊 *آمار و تنظیمات شما*\n\n"
        f"🔍 *محدودیت‌ها:*\n"
        f"┣ جستجوی باقی‌مانده: {remaining}/{rate_limiter.max_requests}\n"
        f"┗ دانلود باقی‌مانده: {downloads_remaining}/{download_rate_limiter.max_downloads}\n\n"
        f"⚙️ *تنظیمات فعال:*\n"
        f"┣ حالت سریع: {'✅' if quick_mode else '❌'}\n"
        f"┣ کیفیت دانلود: {current_quality.value} kbps\n"
        f"┣ نمایش کاور: {'✅' if show_artwork else '❌'}\n"
        f"┣ دانلود خودکار: {'✅' if auto_download else '❌'}\n"
        f"┗ دریافت اعلان: {'✅' if notifications else '❌'}\n\n"
        f"📈 *آمار کلی:*\n"
        f"┣ جستجوها: {total_searches}\n"
        f"┗ دانلودها: {total_downloads}"
    )
    
    markup = [[InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="back_to_settings")]]
    
    if message_id:
        try:
            await edit_or_send(
            bot,
                chat_id=chat_id,
                message_id=message_id,
                text=stats_text,
                reply_markup=InlineKeyboard(markup)
            )
        except:
            await send_message(bot, chat_id, stats_text, reply_markup=markup)
    else:
        await send_message(bot, chat_id, stats_text, reply_markup=markup)


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
    if hasattr(message, 'forward_date') and message.forward_date:
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
    if ":" in text:
        parts = text.split(":", 1)
        type_ = parts[0].lower()
        term = parts[1].strip()
        if type_ in ["artist", "album", "track", "quick"]:
            return type_, term
        else:
            return "track", text
    else:
        return "track", text


# ============================================================================
# Settings Message Functions
# ============================================================================
async def show_settings_message(chat_id: int, user_id: int):
    quick_mode = user_quick_mode.get(user_id, False)
    quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    show_artwork = user_show_artwork.get(user_id, True)
    auto_download = user_auto_download.get(user_id, False)
    notifications = user_notifications.get(user_id, True)
    
    quality_emoji = {
        DownloadQuality.HIGH: "🎵",
        DownloadQuality.MEDIUM: "🎶",
        DownloadQuality.LOW: "🎧"
    }.get(quality, "🎶")
    
    settings_text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"🔹 *حالت سریع:* {'فعال' if quick_mode else 'غیرفعال'}\n"
        f"   ارسال خودکار اولین نتیجه جستجو\n\n"
        f"🔹 *کیفیت دانلود:* {quality_emoji} {quality.value} kbps\n"
        f"   کیفیت بالاتر = حجم بیشتر\n\n"
        f"🔹 *نمایش کاور:* {'فعال' if show_artwork else 'غیرفعال'}\n"
        f"   { 'نمایش تصاویر آلبوم' if show_artwork else 'افزایش سرعت' }\n\n"
        f"🔹 *دانلود خودکار:* {'فعال' if auto_download else 'غیرفعال'}\n"
        f"   { 'دانلود فوری پس از جستجو' if auto_download else 'نمایش اطلاعات قبل از دانلود' }\n\n"
        f"🔹 *دریافت اعلان:* {'فعال' if notifications else 'غیرفعال'}\n"
        f"   { 'دریافت پیام‌های اطلاع‌رسانی' if notifications else 'عدم دریافت پیام‌های اطلاع‌رسانی' }\n\n"
        f"📊 برای مشاهده آمار دقیق، روی دکمه «آمار من» کلیک کنید."
    )
    
    markup = [
        [InlineKeyboardButton(
            text=f"{'✅' if quick_mode else '❌'} حالت سریع", 
            callback_data="toggle_quick_mode"
        )],
        [InlineKeyboardButton(
            text=f"{quality_emoji} کیفیت دانلود ({quality.value}kbps)", 
            callback_data="show_quality_menu"
        )],
        [InlineKeyboardButton(
            text=f"{'🖼️✅' if show_artwork else '🚫🖼️'} نمایش کاور", 
            callback_data="toggle_artwork"
        )],
        [InlineKeyboardButton(
            text=f"{'⚡✅' if auto_download else '⚡❌'} دانلود خودکار", 
            callback_data="toggle_auto_download"
        )],
        [InlineKeyboardButton(
            text=f"{'🔔✅' if notifications else '🔕❌'} دریافت اعلان", 
            callback_data="toggle_notifications"
        )],
        [InlineKeyboardButton(text="📊 آمار من", callback_data="show_stats")],
        [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
    ]
    
    await send_message(bot, chat_id, settings_text, reply_markup=markup)


async def update_settings_message(callback_query: CallbackQuery, user_id: int):
    quick_mode = user_quick_mode.get(user_id, False)
    quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    show_artwork = user_show_artwork.get(user_id, True)
    auto_download = user_auto_download.get(user_id, False)
    notifications = user_notifications.get(user_id, True)
    
    quality_emoji = {
        DownloadQuality.HIGH: "🎵",
        DownloadQuality.MEDIUM: "🎶",
        DownloadQuality.LOW: "🎧"
    }.get(quality, "🎶")
    
    settings_text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"🔹 *حالت سریع:* {'فعال' if quick_mode else 'غیرفعال'}\n"
        f"   ارسال خودکار اولین نتیجه جستجو\n\n"
        f"🔹 *کیفیت دانلود:* {quality_emoji} {quality.value} kbps\n"
        f"   کیفیت بالاتر = حجم بیشتر\n\n"
        f"🔹 *نمایش کاور:* {'فعال' if show_artwork else 'غیرفعال'}\n"
        f"   { 'نمایش تصاویر آلبوم' if show_artwork else 'افزایش سرعت' }\n\n"
        f"🔹 *دانلود خودکار:* {'فعال' if auto_download else 'غیرفعال'}\n"
        f"   { 'دانلود فوری پس از جستجو' if auto_download else 'نمایش اطلاعات قبل از دانلود' }\n\n"
        f"🔹 *دریافت اعلان:* {'فعال' if notifications else 'غیرفعال'}\n"
        f"   { 'دریافت پیام‌های اطلاع‌رسانی' if notifications else 'عدم دریافت پیام‌های اطلاع‌رسانی' }\n\n"
        f"📊 برای مشاهده آمار دقیق، روی دکمه «آمار من» کلیک کنید."
    )
    
    markup = [
        [InlineKeyboardButton(
            text=f"{'✅' if quick_mode else '❌'} حالت سریع", 
            callback_data="toggle_quick_mode"
        )],
        [InlineKeyboardButton(
            text=f"{quality_emoji} کیفیت دانلود ({quality.value}kbps)", 
            callback_data="show_quality_menu"
        )],
        [InlineKeyboardButton(
            text=f"{'🖼️✅' if show_artwork else '🚫🖼️'} نمایش کاور", 
            callback_data="toggle_artwork"
        )],
        [InlineKeyboardButton(
            text=f"{'⚡✅' if auto_download else '⚡❌'} دانلود خودکار", 
            callback_data="toggle_auto_download"
        )],
        [InlineKeyboardButton(
            text=f"{'🔔✅' if notifications else '🔕❌'} دریافت اعلان", 
            callback_data="toggle_notifications"
        )],
        [InlineKeyboardButton(text="📊 آمار من", callback_data="show_stats")]
    ]
    
    try:
        await edit_or_send(
        bot,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            text=settings_text,
            reply_markup=InlineKeyboard(markup)
        )
    except:
        await edit_or_send(
        bot,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            text=settings_text,
            reply_markup=InlineKeyboard(markup)
        )


async def show_quality_menu(callback_query: CallbackQuery, user_id: int):
    current_quality = user_download_quality.get(user_id, DownloadQuality.MEDIUM)
    
    quality_text = (
        "🎵 *انتخاب کیفیت دانلود*\n\n"
        "کیفیت بالاتر = حجم فایل بیشتر و کیفیت صدای بهتر\n\n"
        "📊 *راهنمای کیفیت:*\n"
        "• ۳۲۰ kbps - کیفیت استودیویی (حجم بالا)\n"
        "• ۱۹۲ kbps - کیفیت عالی (مناسب اکثر کاربران)\n"
        "• ۱۲۸ kbps - کیفیت خوب (حجم کمتر)"
    )
    
    markup = [
        [InlineKeyboardButton(
            text=f"{'✅ ' if current_quality == DownloadQuality.HIGH else ''}🎵 ۳۲۰ kbps (بالاترین کیفیت)",
            callback_data="set_quality:320"
        )],
        [InlineKeyboardButton(
            text=f"{'✅ ' if current_quality == DownloadQuality.MEDIUM else ''}🎶 ۱۹۲ kbps (کیفیت عالی)",
            callback_data="set_quality:192"
        )],
        [InlineKeyboardButton(
            text=f"{'✅ ' if current_quality == DownloadQuality.LOW else ''}🎧 ۱۲۸ kbps (حجم کمتر)",
            callback_data="set_quality:128"
        )],
        [InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="back_to_settings")],
    ]
    
    try:
        await edit_or_send(
        bot,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            text=quality_text,
            reply_markup=InlineKeyboard(markup)
        )
    except:
        await edit_or_send(
        bot,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            text=quality_text,
            reply_markup=InlineKeyboard(markup)
        )


# ============================================================================
# Bale Bot Initialization & Handlers
# ============================================================================
bot = Client(token=BOT_TOKEN)


@bot.on_initialize()
async def on_initialize():
    global HTTP_SESSION
    HTTP_SESSION = aiohttp.ClientSession()
    await api_client._request('get_required_channels', {})
    logger.info(f"Bot started with enhanced settings")
    asyncio.create_task(cleanup_caches())
    asyncio.create_task(clear_expired_cache())


@bot.on_shutdown()
async def on_shutdown():
    global HTTP_SESSION
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()
    if api_client.session and not api_client.session.closed:
        await api_client.session.close()
    logger.info("Bot shutdown complete")


@bot.on_disconnect()
async def on_disconnect():
    global HTTP_SESSION
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()


@bot.on_message()
async def handle_message(message):
    if message.author.is_bot:
        return

    await register_user(message)

    if message.chat.type == "channel":
        await process_broadcast_message(message)
        return

    if "abraava" in str(message.author.username):
        return

    is_group = message.chat.type in ["group", "supergroup", "channel"]
    msg_text = message.content or ""
    user_id = message.author.id
    chat_id = message.chat.id
    
    if not is_group:
        is_member, missing = await verify_all_memberships(user_id)
        if not is_member and not msg_text.startswith("/start"):
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

    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention not in msg_text:
            return
        if not is_valid_message(message):
            return
        msg_text = msg_text.replace(bot_mention, "").strip()
        if len(msg_text) > 100:
            await reply_message(message, f"⚠️ *متن پیام خیلی طولانی است*\n\nحداکثر ۱۰۰ کاراکتر مجاز است.")
            return
    else:
        is_member, missing = await verify_all_memberships(user_id)
        if not is_member and not msg_text.startswith("/start"):
            channels_text = "\n".join([f"{ch}" for ch in missing])
            await reply_message(message, f"⚠️ *برای استفاده از ربات باید در کانال‌های زیر عضو شوید:*\n\n{channels_text}\n\nپس از عضویت، دوباره تلاش کنید.")
            return
        if not is_valid_message(message):
            await reply_message(message, f"⚠️ *فرمت پیام نامعتبر*\n\nفقط پیام‌های متنی زیر ۱۰۰ کاراکتر قابل پردازش هستند.\nلطفاً بدون عکس، ویدیو، فایل و فوروارد پیام دهید.")
            return

    if msg_text.startswith("/start"):
        welcome_text = (
            f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
            f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n\n"
            f"✨ *امکانات ربات:*\n"
            f"• جستجو در آیتونز و دانلود از یوتیوب موزیک\n"
            f"• قابلیت دانلود آلبوم به صورت یکجا\n"
            f"• تنظیم کیفیت دانلود (۳۲۰/۱۹۲/۱۲۸ kbps)\n"
            f"• حالت سریع و دانلود خودکار\n"
            f"• غیرفعال کردن کاور آلبوم برای افزایش سرعت\n\n"
            f"🔧 برای تنظیمات از `/settings` استفاده کنید.\n"
            f"📊 برای مشاهده آمار از `/stats` استفاده کنید.\n"
            f"🆘 برای راهنما از `/help` استفاده کنید."
        )
        if INFO_CHANNEL_ID:
            welcome_text += f"\n\n📢 *کانال اطلاع‌رسانی:* ble.ir/join/4T95Zt7P5X"
        await reply_message(message, welcome_text)

    elif msg_text.startswith("/help"):
        await reply_message(message,
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            f"🔍 *جستجو:*\n"
            f"• `/search [نام]` - جستجوی عمومی\n"
            f"• `/track [نام]` - جستجوی آهنگ\n"
            f"• `/album [نام]` - جستجوی آلبوم\n"
            f"• `/artist [نام]` - جستجوی هنرمند\n"
            f"• `/quick [نام]` - دانلود سریع اولین نتیجه\n\n"
            f"⚙️ *تنظیمات:*\n"
            f"• `/settings` - تنظیمات ربات\n"
            f"• `/stats` - آمار کاربری\n\n"
            f"💡 *نکات:*\n"
            f"• در گروه‌ها حتما ربات را تگ کنید\n"
            f"• محدودیت: {rate_limiter.max_requests} جستجو در دقیقه\n"
            f"• محدودیت: {download_rate_limiter.max_downloads} دانلود در ساعت"
        )

    elif msg_text.startswith("/about"):
        await reply_message(message,
            f"ℹ️ *درباره {BOT_NAME}*\n\n"
            f"ربات دانلود موزیک با قابلیت جستجو در iTunes و دانلود از YouTube Music\n\n"
            f"✨ *ویژگی‌ها:*\n"
            f"• دانلود با کیفیت ۳۲۰/۱۹۲/۱۲۸ kbps\n"
            f"• دانلود آلبوم به صورت یکجا\n"
            f"• تگ‌گذاری خودکار (کاور و اطلاعات)\n"
            f"• قابلیت غیرفعال کردن کاور برای سرعت بیشتر\n"
            f"• دانلود خودکار در حالت سریع\n\n"
            f"📝 *نسخه:* 2.0\n"
            f"👨‍💻 *توسعه:* ابرآوا"
        )

    elif msg_text.startswith("/settings"):
        await show_settings_message(chat_id, user_id)

    elif msg_text.startswith("/stats"):
        await show_user_stats(user_id, chat_id)

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
    message_id = callback_query.message.id
    is_group = callback_query.message.chat.type in ["group", "supergroup"]

    if data == "ignore":
        await bot.answer_callback_query(callback_query.id)
        return

    if data == "close":
        try:
            if message_id in MESSAGE_OWNER:
                MESSAGE_OWNER.pop(message_id, None)
            await callback_query.message.delete()
        except:
            pass
        return

    # Settings toggles
    if data == "toggle_quick_mode":
        current = user_quick_mode.get(user_id, False)
        user_quick_mode[user_id] = not current
        await api_client.update_quick_mode(user_id, not current)
        await update_settings_message(callback_query, user_id)
        return
    
    if data == "toggle_artwork":
        current = user_show_artwork.get(user_id, True)
        user_show_artwork[user_id] = not current
        await api_client.update_show_artwork(user_id, not current)
        await update_settings_message(callback_query, user_id)
        return
    
    if data == "toggle_auto_download":
        current = user_auto_download.get(user_id, False)
        user_auto_download[user_id] = not current
        await api_client.update_auto_download(user_id, not current)
        await update_settings_message(callback_query, user_id)
        return
    
    if data == "toggle_notifications":
        current = user_notifications.get(user_id, True)
        user_notifications[user_id] = not current
        await api_client.update_notifications(user_id, not current)
        await update_settings_message(callback_query, user_id)
        return
    
    if data == "show_stats":
        await show_user_stats(user_id, chat_id, message_id)
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
        await api_client.update_download_quality(user_id, quality_value)
        await update_settings_message(callback_query, user_id)
        return
    
    if data == "back_to_settings":
        await update_settings_message(callback_query, user_id)
        return

    # Handle retry callbacks
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

    # Handle album download cancellation
    if data.startswith("cancel_album:"):
        parts = data.split(":")
        if len(parts) >= 3:
            owner_id_from_cb = int(parts[1])
            collection_id = int(parts[2])
            if user_id != owner_id_from_cb:
                await bot.answer_callback_query(callback_query.id, "❌ شما مالک این دانلود نیستید.", show_alert=True)
                return
            album_tracker.cancel_download(owner_id_from_cb, collection_id)
            await update_status_with_close(
                callback_query.message,
                "⏹️ *در حال توقف دانلود آلبوم...*\nلطفاً چند لحظه صبر کنید."
            )
            await bot.answer_callback_query(callback_query.id)
        else:
            await bot.answer_callback_query(callback_query.id, "❌ خطا در اطلاعات لغو", show_alert=True)
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
                    await bot.answer_callback_query(callback_query.id, "❌ این جستجو متعلق به شما نیست.", show_alert=True)
                    return
                await send_search_page(chat_id, cached["type"], cached["term"], cached["results"], page,
                                       callback_query.message, owner_id=cached["owner_id"])
            else:
                await bot.answer_callback_query(callback_query.id, "⏳ نتایج جستجو منقضی شده‌اند.", show_alert=True)
        elif data.startswith("refine:"):
            entity = parts[1]
            term = parts[2]
            await handle_search_command(chat_id, user_id, entity, term, owner_id=user_id)
        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist_page(chat_id, artist_id, page, callback_query.message, user_id)
        elif data.startswith("collection:"):
            collection_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_collection_page(chat_id, collection_id, page, callback_query.message, user_id)
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track_page(chat_id, track_id, callback_query.message, user_id)
        elif data.startswith("download:"):
            track_id = int(parts[1])
            can_dl, wait_sec = await download_rate_limiter.can_download(user_id)
            if not can_dl:
                await bot.answer_callback_query(callback_query.id, f"⏳ محدودیت دانلود: {wait_sec} ثانیه صبر کنید", show_alert=True)
                return
            await bot.answer_callback_query(callback_query.id, "در حال پردازش دانلود...")
            asyncio.create_task(download_and_send_single_track(bot, chat_id, track_id, user_id))
      
        elif data.startswith("download_album:"):
            collection_id = int(parts[1])
            chat = await bot.get_chat(chat_id)
            if chat.type == "group" or chat.type == "supergroup":
                await bot.answer_callback_query(callback_query.id, "❌ دانلود آلبوم در گروه‌ها مجاز نیست.", show_alert=True)
                return
            can_dl, wait_sec = await download_rate_limiter.can_download(user_id)
            if not can_dl:
                await bot.answer_callback_query(callback_query.id, f"⏳ محدودیت دانلود: {wait_sec} ثانیه صبر کنید", show_alert=True)
                return
            await bot.answer_callback_query(callback_query.id, "📀 در حال آماده‌سازی دانلود آلبوم...")

            collection_data = await get_or_crawl_collection(collection_id, None, False)
            tracks_data = await get_or_crawl_collection_tracks(collection_id)
            tracks = tracks_data["results"] if tracks_data else []

            if not tracks:
                await bot.answer_callback_query(callback_query.id, "❌ هیچ قطعه‌ای در این آلبوم یافت نشد.", show_alert=True)
                return

            collection_name = collection_data['results'][0].get('collectionName', 'آلبوم') if collection_data else 'آلبوم'
            status_msg = await send_message(bot, chat_id, f"🎵 *شروع دانلود آلبوم: {collection_name}*\nدر حال آماده‌سازی...")
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
        logger.error(f"Error handling callback {data}: {e}")
        await bot.answer_callback_query(callback_query.id, f"❌ خطا: {str(e)[:50]}", show_alert=True)


def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    logger.info(f'"{BOT_NAME}" is starting...')

    while True:
        try:
            bot.run()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.exception(f"Bot crashed: {e}")
            logger.info("Restarting bot in 1 minutes...")
            time.sleep(60)
        finally:
            logger.info("Bot shutdown complete")