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
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Tuple
from dataclasses import dataclass
from enum import Enum
import signal
import sys
from balethon import Client
from balethon.objects import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboard

from config import BOT_NAME, FOOTER, OFFLINE_MODE, ITEMS_PER_PAGE, BOT_TOKEN, DB_CHANNEL_ID, INFO_CHANNEL_ID, logger, \
    BROADCAST_CHANNELS, ITUNES_BASE_URL, API_BASE_URL, API_TOKEN
from crawlers.itunes import search_itunes, lookup_itunes, fetch_itunes, set_mirror, get_mirror
from crawlers.utils import get_or_crawl_collection, \
    get_or_crawl_artist, get_track, get_or_crawl_collection_tracks, get_or_crawl_artist_collections
from crawlers.youtube import download_audio, search_youtube_track, get_artist_image
from utils import tag_mp3, send_error_with_retry, send_message, send_photo, send_audio, send_voice, \
    update_status_with_close, reply_message, create_pagination_row, get_high_res_artwork, format_duration, generate_search_hash

# ============================================================================
# Bale Upload Health Status
# ============================================================================
class BaleUploadHealth:
    """Smart health monitor for Bale upload service"""
    def __init__(self):
        self.has_issue = False
        self.notification_msg_id = None
        self.notified = False
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.MAX_FAILURES = 3
        self.MIN_SUCCESSES = 2
        self.last_failure_time = 0
        self.last_success_time = 0
    
    def record_success(self):
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.last_success_time = time.time()
        
        if self.has_issue and self.consecutive_successes >= self.MIN_SUCCESSES:
            self.has_issue = False
            self.consecutive_successes = 0
            return True  # Issue resolved
        return False  # Still has issue or never had issue
    
    def record_failure(self):
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        
        if not self.has_issue and self.consecutive_failures >= self.MAX_FAILURES:
            self.has_issue = True
            return True  # Issue detected
        return False  # No issue yet or already has issue
    
    def should_use_url(self) -> bool:
        """If issue exists or recent failure (within last 30 seconds), use URL"""
        if self.has_issue:
            return True
        # If last failure was very recent (30s), be cautious
        if time.time() - self.last_failure_time < 30:
            return True
        return False

bale_health = BaleUploadHealth()

# ============================================================================
# API Client for PHP Backend
# ============================================================================
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

    async def log_search(self, user_id: int, search_type: str, search_term: str, result_count: int) -> Dict:
        return await self._request('log_search', {
            'user_id': user_id,
            'search_type': search_type,
            'search_term': search_term,
            'result_count': result_count
        })

    async def log_download(self, user_id: int, track_id: str, track_name: str, artist_name: str,
                           album_name: str = '', file_size: int = 0, download_source: str = 'youtube') -> Dict:
        return await self._request('log_download', {
            'user_id': user_id,
            'track_id': track_id,
            'track_name': track_name,
            'artist_name': artist_name,
            'album_name': album_name,
            'file_size': file_size,
            'download_source': download_source
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
# Cache Management
# ============================================================================
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
ARTWORK_CACHE_DIR = CACHE_DIR / "artwork"
ARTWORK_CACHE_DIR.mkdir(exist_ok=True)

SEARCH_CACHE_TTL = 600
MESSAGE_OWNER_TTL = 600
SEARCH_CACHE_MAX_ITEMS = 100

SEARCH_CACHE = {}
MESSAGE_OWNER = {}
user_quick_mode = {}

# ============================================================================
# Helper Functions
# ============================================================================
def get_cache_path(key: str, prefix: str = "") -> Path:
    hash_key = hashlib.md5(f"{prefix}:{key}".encode()).hexdigest()
    return CACHE_DIR / f"{hash_key}.cache"

async def cache_get(key: str, ttl: int, prefix: str = "") -> Optional[Any]:
    try:
        path = get_cache_path(key, prefix)
        if not path.exists():
            return None
        with open(path, 'rb') as f:
            data = pickle.load(f)
        if time.time() - data["timestamp"] > ttl:
            path.unlink(missing_ok=True)
            return None
        return data["data"]
    except Exception:
        return None

async def cache_set(key: str, data: Any, ttl: int, prefix: str = ""):
    try:
        path = get_cache_path(key, prefix)
        with open(path, 'wb') as f:
            pickle.dump({"data": data, "timestamp": time.time(), "ttl": ttl}, f)
    except Exception as e:
        logger.error(f"Cache set failed: {e}")

async def get_artwork_bytes(url: str) -> Optional[bytes]:
    """Download artwork bytes from URL"""
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.error(f"Artwork download failed: {e}")
    return None

async def notify_bale_issue(detected: bool, error: str = ""):
    """Send notification to info channel about Bale status"""
    if not INFO_CHANNEL_ID:
        return
    
    try:
        if detected and not bale_health.notified:
            msg = await send_message(
                bot, INFO_CHANNEL_ID,
                f"⚠️ *اختلال در سرویس آپلود بله*\n\n"
                f"ربات با خطای ۵۰۰ مواجه شده است.\n"
                f"تا رفع مشکل، تصاویر با URL مستقیم ارسال می‌شوند.\n\n"
                f"📝 {error[:200]}\n"
                f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#اطلاع_رسانی #مشکل_بله"
            )
            if msg:
                bale_health.notification_msg_id = msg.id
                bale_health.notified = True
                
        elif not detected and bale_health.notified:
            await send_message(
                bot, INFO_CHANNEL_ID,
                f"✅ *مشکل آپلود بله برطرف شد*\n\n"
                f"ربات به حالت عادی بازگشت.\n"
                f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#اطلاع_رسانی #رفع_مشکل"
            )
            if bale_health.notification_msg_id:
                try:
                    await bot.delete_message(INFO_CHANNEL_ID, bale_health.notification_msg_id)
                except:
                    pass
            bale_health.notified = False
            bale_health.notification_msg_id = None
    except Exception as e:
        logger.error(f"Notification failed: {e}")

# ============================================================================
# Artwork Mirror Management - Smart Collection-based Mirror
# ============================================================================
async def get_artwork_mirror(entity_type: str, entity_id: int, collection_id: int = None) -> Optional[str]:
    """
    Get artwork mirror URL
    - For tracks: uses collection mirror (if collection_id provided)
    - For collections: uses collection mirror directly
    """
    mirror_type = entity_type
    mirror_id = entity_id
    
    if entity_type == 'track' and collection_id:
        mirror_type = 'collection'
        mirror_id = collection_id
        logger.debug(f"Track {entity_id} using collection {collection_id} mirror")
    
    data = await get_mirror(mirror_type, str(mirror_id), 'artworkUrl')
    if data.get("mirrors", {}).get('artworkUrl', False):
        return data["mirrors"]['artworkUrl']['url']
    return None

async def set_artwork_mirror(entity_type: str, entity_id: int, collection_id: int, file_id: str):
    """
    Set artwork mirror
    - For tracks: saves to collection mirror (not track mirror)
    - For collections: saves to collection mirror
    """
    mirror_type = entity_type
    mirror_id = entity_id
    
    if entity_type == 'track' and collection_id:
        mirror_type = 'collection'
        mirror_id = collection_id
        logger.info(f"Saving track artwork to collection {collection_id} mirror")
    
    await set_mirror(mirror_type, str(mirror_id), 'artworkUrl',
                     f'https://tapi.bale.ai/file/bot<token>/{file_id}')

async def get_display_artwork(artwork_url: str, entity_type: str, entity_id: int, collection_id: int = None) -> Tuple[Optional[str], Optional[bytes]]:
    """Get artwork for display - returns (url_or_file_id, artwork_bytes)"""
    if not artwork_url:
        return None, None
    
    # Try mirror first
    mirror = await get_artwork_mirror(entity_type, entity_id, collection_id)
    if mirror:
        logger.info(f"Using mirror for {entity_type} {entity_id}")
        return mirror, None
    
    # Download fresh
    logger.info(f"Downloading artwork for {entity_type} {entity_id}")
    bytes_data = await get_artwork_bytes(artwork_url)
    return artwork_url, bytes_data

async def get_tagging_artwork(artwork_url: str, entity_type: str, entity_id: int, collection_id: int = None) -> Optional[bytes]:
    """Get artwork bytes for MP3 tagging"""
    if not artwork_url:
        return None
    
    # Try mirror first
    mirror = await get_artwork_mirror(entity_type, entity_id, collection_id)
    if mirror:
        logger.info(f"Using mirror for tagging")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(mirror, timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.error(f"Mirror download failed: {e}")
    
    # Fallback to direct download
    return await get_artwork_bytes(artwork_url)

# ============================================================================
# Channel Membership
# ============================================================================
async def check_channel_membership(user_id: int, channel_id: str) -> bool:
    try:
        chat_member = await bot.get_chat_member(channel_id, user_id)
        return chat_member and chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Membership check failed for {user_id} in {channel_id}: {e}")
        return False

async def verify_memberships(user_id: int) -> Tuple[bool, List[Dict]]:
    result = await api_client.get_required_channels()
    if not result.get('success'):
        return True, []
    
    missing = []
    for channel in result.get('data', []):
        if not await check_channel_membership(user_id, channel.get('channel_id')):
            missing.append(channel)
    return len(missing) == 0, missing

# ============================================================================
# Rate Limiting
# ============================================================================
class RateLimiter:
    def __init__(self, max_req: int = 30, window: int = 60):
        self.max_req = max_req
        self.window = window
        self.users: Dict[int, List[float]] = defaultdict(list)
    
    async def check(self, user_id: int) -> Tuple[bool, int]:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.window]
        if len(self.users[user_id]) >= self.max_req:
            wait = int(self.window - (now - min(self.users[user_id])))
            return False, wait
        self.users[user_id].append(now)
        return True, 0

class DownloadLimiter:
    def __init__(self, max_dl: int = 100, window: int = 3600):
        self.max_dl = max_dl
        self.window = window
        self.users: Dict[int, List[float]] = defaultdict(list)
    
    async def can_download(self, user_id: int) -> Tuple[bool, int]:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.window]
        if len(self.users[user_id]) >= self.max_dl:
            wait = int(self.window - (now - min(self.users[user_id])))
            return False, wait
        return True, 0
    
    def record(self, user_id: int):
        self.users[user_id].append(time.time())

rate_limiter = RateLimiter()
download_limiter = DownloadLimiter()

# ============================================================================
# Album Download Tracker
# ============================================================================
class AlbumTracker:
    def __init__(self):
        self.active = {}
        self.locks = {}
    
    async def acquire(self, user_id: int, album_id: int) -> bool:
        key = (user_id, album_id)
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        try:
            await asyncio.wait_for(self.locks[key].acquire(), timeout=5)
            return True
        except asyncio.TimeoutError:
            return False
    
    def release(self, user_id: int, album_id: int):
        key = (user_id, album_id)
        if key in self.locks and self.locks[key].locked():
            self.locks[key].release()
    
    def start(self, user_id: int, album_id: int, name: str, total: int, msg):
        self.active[(user_id, album_id)] = {
            "name": name, "total": total, "msg": msg,
            "tracks": [], "current": 0, "success": 0, "failed": 0,
            "cancelled": False, "start_time": time.time(), "artwork": None
        }
    
    def set_artwork(self, user_id: int, album_id: int, artwork: bytes):
        key = (user_id, album_id)
        if key in self.active:
            self.active[key]["artwork"] = artwork
    
    def get_artwork(self, user_id: int, album_id: int) -> Optional[bytes]:
        key = (user_id, album_id)
        return self.active.get(key, {}).get("artwork")
    
    def add_track(self, user_id: int, album_id: int, name: str):
        key = (user_id, album_id)
        if key in self.active:
            self.active[key]["tracks"].append({"name": name, "success": False})
    
    def update_track(self, user_id: int, album_id: int, name: str, success: bool):
        key = (user_id, album_id)
        if key in self.active:
            for t in self.active[key]["tracks"]:
                if t["name"] == name:
                    t["success"] = success
                    break
            self.active[key]["current"] += 1
            if success:
                self.active[key]["success"] += 1
            else:
                self.active[key]["failed"] += 1
    
    def get_progress(self, user_id: int, album_id: int) -> str:
        key = (user_id, album_id)
        if key not in self.active:
            return ""
        a = self.active[key]
        elapsed = time.time() - a["start_time"]
        eta = ""
        if a["current"] > 0:
            avg = elapsed / a["current"]
            remaining = avg * (a["total"] - a["current"])
            eta = f"\n⏱️ زمان باقیمانده: {int(remaining)} ثانیه"
        
        return (f"📀 *دانلود آلبوم: {a['name']}*\n"
                f"🎵 در حال دانلود: {a['current'] + 1 if a['current'] < a['total'] else a['total']}/{a['total']}\n"
                f"✅ موفق: {a['success']} | ❌ ناموفق: {a['failed']}{eta}")
    
    def cancel(self, user_id: int, album_id: int):
        key = (user_id, album_id)
        if key in self.active:
            self.active[key]["cancelled"] = True
    
    def is_cancelled(self, user_id: int, album_id: int) -> bool:
        key = (user_id, album_id)
        return self.active.get(key, {}).get("cancelled", True)
    
    def finish(self, user_id: int, album_id: int):
        key = (user_id, album_id)
        if key in self.active:
            del self.active[key]
        self.release(user_id, album_id)

album_tracker = AlbumTracker()

# ============================================================================
# Core Functions
# ============================================================================
async def send_audio_smart(bot: Client, chat_id: int, audio_path: str, caption: str, track_id: str, max_retries: int = 3):
    """Smart audio sender with health tracking"""
    abs_path = os.path.abspath(audio_path)
    if not await asyncio.to_thread(os.path.exists, abs_path):
        raise FileNotFoundError(f"File not found: {abs_path}")
    
    markup = [[
        InlineKeyboardButton("📂 نمایش در مینی اپ", web_app=f"https://player.abraava.ir?id={track_id}"),
        InlineKeyboardButton("📋 کپی پیوند", copy_text=f"https://player.abraava.ir?id={track_id}")
    ]]
    
    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_path, 'rb') as f:
                msg = await send_audio(bot, chat_id, audio=f, caption=caption, reply_markup=markup)
            
            # Success
            if bale_health.record_success():
                await notify_bale_issue(False)
            
            # Cache audio
            await set_mirror('track', str(track_id), 'audioUrl',
                            f'https://tapi.bale.ai/file/bot<token>/{msg.audio.id}')
            return msg
            
        except Exception as e:
            error = str(e)
            logger.warning(f"Upload attempt {attempt} failed: {error[:100]}")
            
            if "500" in error or "Internal Server Error" in error:
                if bale_health.record_failure():
                    await notify_bale_issue(True, error[:200])
            
            if attempt < max_retries:
                await asyncio.sleep(attempt * 2)
            else:
                raise Exception("آپلود با مشکل مواجه شد. لطفاً بعداً تلاش کنید.")

async def download_track(bot: Client, chat_id: int, track_id: int, user_id: int,
                         status_msg: Message = None, is_batch: bool = False, album_artwork: bytes = None):
    """Download and send single track"""
    if not is_batch or not status_msg:
        status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود...*")
    
    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await send_error_with_retry(bot, chat_id, "خطا در دریافت اطلاعات آهنگ.", f"retry:download:{track_id}", status_msg)
        return
    
    track = track_data["results"][0]
    
    # Build caption
    duration = format_duration(track.get('trackTimeMillis', 0))
    caption = (f"🎵 *{track.get('trackName', 'Unknown')}*\n"
               f"🎤 {track.get('artistName', 'Unknown')}\n"
               f"📀 {track.get('collectionName', 'Unknown')}\n"
               f"⏱️ {duration}")
    
    # Check audio cache
    mirror = await get_mirror('track', str(track_id), 'audioUrl')
    if mirror.get("mirrors", {}).get('audioUrl'):
        try:
            await update_status_with_close(status_msg, "📤 *ارسال از کش...*")
            await send_audio(bot, chat_id, audio=mirror["mirrors"]['audioUrl']['url'].split('<token>/')[1], 
                           caption=caption)
            await status_msg.delete()
            await api_client.log_download(user_id, str(track_id), track.get('trackName', ''), 
                                        track.get('artistName', ''), track.get('collectionName', ''), 0, 'cache')
            return
        except Exception as e:
            logger.error(f"Cache failed: {e}")
    
    if OFFLINE_MODE:
        await send_error_with_retry(bot, chat_id, "بات در حالت آفلاین است.", f"retry:download:{track_id}", status_msg)
        return
    
    # Get artwork for tagging
    cover = album_artwork
    if not cover and not is_batch:
        artwork_url = get_high_res_artwork(track.get("artworkUrl100"), 600)
        if artwork_url:
            cover = await get_tagging_artwork(artwork_url, 'track', track_id, track.get('collectionId'))
    
    # Search and download from YouTube
    await update_status_with_close(status_msg, "🔍 *جستجوی منبع باکیفیت...*")
    
    video_id = await search_youtube_track(
        track.get('trackName', ''),
        track.get('artistName', ''),
        track.get('collectionName', ''),
        track.get('releaseDate', '').split('-')[0] if track.get('releaseDate') else ''
    )
    
    if not video_id:
        await send_error_with_retry(bot, chat_id, "منبع یافت نشد.", f"retry:download:{track_id}", status_msg)
        return
    
    # Download and process
    await update_status_with_close(status_msg, "⏳ *در حال دانلود و پردازش...*")
    
    mp3_path = await download_audio(f"https://music.youtube.com/watch?v={video_id}")
    if not mp3_path or not os.path.exists(mp3_path):
        await send_error_with_retry(bot, chat_id, "دانلود ناموفق بود.", f"retry:download:{track_id}", status_msg)
        return
    
    # Tag MP3
    await asyncio.to_thread(tag_mp3, mp3_path, track, cover if isinstance(cover, bytes) else None)
    
    # Upload
    await update_status_with_close(status_msg, "☁️ *در حال آپلود...*")
    await send_audio_smart(bot, chat_id, mp3_path, caption, str(track_id))
    
    # Log and cleanup
    await api_client.log_download(user_id, str(track_id), track.get('trackName', ''), 
                                track.get('artistName', ''), track.get('collectionName', ''), 
                                int(os.path.getsize(mp3_path) / 1024), 'youtube')
    download_limiter.record(user_id)
    
    try:
        await status_msg.delete()
    except:
        pass
    
    # Cleanup temp files
    try:
        shutil.rmtree(os.path.dirname(mp3_path), ignore_errors=True)
    except:
        pass

async def download_album(bot: Client, chat_id: int, album_id: int, user_id: int, 
                         name: str, tracks: List[dict], status_msg: Message):
    """Download full album with shared artwork"""
    if not await album_tracker.acquire(user_id, album_id):
        await update_status_with_close(status_msg, "❌ *دانلود آلبوم در حال انجام است*")
        album_tracker.finish(user_id, album_id)
        return
    
    album_tracker.start(user_id, album_id, name, len(tracks), status_msg)
    
    # Download album artwork once
    if tracks:
        artwork_url = get_high_res_artwork(tracks[0].get("artworkUrl100"), 600)
        if artwork_url:
            artwork = await get_tagging_artwork(artwork_url, 'collection', album_id)
            album_tracker.set_artwork(user_id, album_id, artwork)
    
    for track in tracks:
        album_tracker.add_track(user_id, album_id, track.get('trackName', 'Unknown'))
    
    cancel_btn = [[InlineKeyboardButton("❌ لغو دانلود", callback_data=f"cancel_album:{user_id}:{album_id}")]]
    
    success_count = 0
    for track in tracks:
        if album_tracker.is_cancelled(user_id, album_id):
            await update_status_with_close(status_msg, f"⏹️ *دانلود لغو شد*\n{album_tracker.get_progress(user_id, album_id)}")
            break
        
        track_id = track.get('trackId')
        if not track_id:
            continue
        
        can_dl, wait = await download_limiter.can_download(user_id)
        if not can_dl:
            await update_status_with_close(status_msg, f"⏳ *محدودیت دانلود: {wait} ثانیه صبر کنید*")
            break
        
        try:
            await download_track(bot, chat_id, track_id, user_id, status_msg, 
                               is_batch=True, album_artwork=album_tracker.get_artwork(user_id, album_id))
            success_count += 1
            album_tracker.update_track(user_id, album_id, track.get('trackName'), True)
        except Exception as e:
            logger.error(f"Track failed: {e}")
            album_tracker.update_track(user_id, album_id, track.get('trackName'), False)
        
        await update_status_with_close(status_msg, album_tracker.get_progress(user_id, album_id), 
                                     reply_markup=cancel_btn, no=True)
        await asyncio.sleep(1)
    
    final = (f"✅ *دانلود آلبوم {name} به پایان رسید*\n\n"
             f"📊 موفق: {success_count}/{len(tracks)}")
    await edit_or_send(bot, chat_id, status_msg, final, owner_id=user_id)
    album_tracker.finish(user_id, album_id)

# ============================================================================
# Display Functions
# ============================================================================
async def edit_or_send(bot: Client, chat_id: int, msg_to_edit: Optional[Message], text: str,
                       markup=None, artwork_url: str = None, entity_type: str = None,
                       entity_id: int = None, collection_id: int = None, owner_id: int = None):
    """Smart message sender with intelligent artwork handling"""
    if markup is None:
        markup = []
    
    msg = None
    
    if artwork_url and entity_type and entity_id:
        try:
            url_or_file, bytes_data = await get_display_artwork(artwork_url, entity_type, entity_id, collection_id)
            
            if url_or_file:
                use_url = bale_health.should_use_url()
                
                if use_url:
                    # Use URL directly (avoid upload during issues)
                    msg = await send_photo(bot, chat_id, photo=url_or_file, caption=text, reply_markup=markup)
                else:
                    # Try to upload as file
                    try:
                        if isinstance(url_or_file, str) and 'tapi.bale.ai' in url_or_file:
                            msg = await send_photo(bot, chat_id, photo=url_or_file, caption=text, reply_markup=markup)
                        elif bytes_data:
                            photo_io = io.BytesIO(bytes_data)
                            photo_io.name = "artwork.jpg"
                            msg = await send_photo(bot, chat_id, photo=photo_io, caption=text, reply_markup=markup)
                        else:
                            msg = await send_photo(bot, chat_id, photo=url_or_file, caption=text, reply_markup=markup)
                        
                        # Cache the uploaded file
                        if bytes_data and msg and msg.photo:
                            await set_artwork_mirror(entity_type, entity_id, collection_id, msg.photo[0].id)
                            
                    except Exception as e:
                        if "500" in str(e):
                            bale_health.record_failure()
                            await notify_bale_issue(True, str(e)[:200])
                            # Retry with URL
                            msg = await send_photo(bot, chat_id, photo=url_or_file, caption=text, reply_markup=markup)
                        else:
                            raise
            else:
                msg = await send_message(bot, chat_id, text=text, reply_markup=markup, no=True)
                
        except Exception as e:
            logger.error(f"Artwork send failed: {e}")
            msg = await send_message(bot, chat_id, text=text, reply_markup=markup, no=True)
    else:
        msg = await send_message(bot, chat_id, text=text, reply_markup=markup)
    
    if owner_id and msg and msg.chat.type in ["group", "supergroup"]:
        MESSAGE_OWNER[msg.id] = (owner_id, time.time())
    
    if msg_to_edit:
        try:
            await msg_to_edit.delete()
        except:
            pass
    
    return msg

async def show_album(chat_id: int, album_id: int, page: int = 1, msg_to_edit: Message = None, owner_id: int = None):
    """Show album page"""
    status = await send_message(bot, chat_id, "🔄 *در حال بارگذاری آلبوم...*")
    
    try:
        album_data = await get_or_crawl_collection(album_id, status)
        tracks_data = await get_or_crawl_collection_tracks(album_id)
        
        if not album_data:
            await send_error_with_retry(bot, chat_id, "آلبوم یافت نشد.", f"retry:album:{album_id}", status)
            return
        
        album = album_data['results'][0]
        tracks = tracks_data.get("results", []) if tracks_data else []
        
        # Build text
        release = album.get('releaseDate', 'نامشخص')[:10] if album.get('releaseDate') else 'نامشخص'
        text = (f"*📀 آلبوم:* {album.get('collectionName', 'نامشخص')}\n"
                f"*🎤 هنرمند:* {album.get('artistName', 'نامشخص')}\n"
                f"*📅 انتشار:* {release}\n"
                f"*🎭 سبک:* {album.get('primaryGenreName', 'نامشخص')}\n")
        
        # Paginate tracks
        total = len(tracks)
        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(1, min(page, total_pages))
        start = (page - 1) * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_tracks = tracks[start:end]
        
        if tracks:
            text += f"\n*🎵 قطعات ({total}):*\n"
            for i, track in enumerate(page_tracks, start + 1):
                dur = format_duration(track.get('trackTimeMillis', 0))
                text += f"{i}. {track.get('trackName', 'نامشخص')} ({dur})\n"
        
        # Build markup
        markup = []
        for track in page_tracks:
            markup.append([InlineKeyboardButton(
                f"🎵 {track.get('trackName', 'نامشخص')[:40]}",
                callback_data=f"track:{track['trackId']}"
            )])
        
        if total_pages > 1:
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"collection:{album_id}:{page-1}"))
            if page < total_pages:
                row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"collection:{album_id}:{page+1}"))
            if row:
                markup.append(row)
        
        # Download album button (only in private)
        chat = await bot.get_chat(chat_id)
        if chat.type not in ["group", "supergroup"] and tracks:
            markup.append([InlineKeyboardButton("⬇️ دانلود کل آلبوم", callback_data=f"download_album:{album_id}")])
        
        if album.get('artistId'):
            markup.append([InlineKeyboardButton("🎤 مشاهده هنرمند", callback_data=f"artist:{album['artistId']}:1")])
        
        markup.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:collection:{album_id}")])
        
        artwork = get_high_res_artwork(album.get("artworkUrl100"))
        await edit_or_send(bot, chat_id, msg_to_edit, text, markup, artwork, 'collection', album_id, owner_id=owner_id)
        await status.delete()
        
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"retry:album:{album_id}", status)

async def show_track(chat_id: int, track_id: int, msg_to_edit: Message = None, owner_id: int = None):
    """Show track page"""
    status = await send_message(bot, chat_id, "🔄 *در حال بارگذاری آهنگ...*")
    
    try:
        data = await get_track(track_id, status)
        if not data or not data.get("results"):
            await send_error_with_retry(bot, chat_id, "آهنگ یافت نشد.", f"retry:track:{track_id}", status)
            return
        
        track = data["results"][0]
        duration = format_duration(track.get('trackTimeMillis', 0))
        release = track.get('releaseDate', 'نامشخص')[:10] if track.get('releaseDate') else 'نامشخص'
        
        text = (f"*🎵 آهنگ:* {track.get('trackName', 'نامشخص')}\n"
                f"*🎤 هنرمند:* {track.get('artistName', 'نامشخص')}\n"
                f"*📀 آلبوم:* {track.get('collectionName', 'نامشخص')}\n"
                f"*⏱️ مدت:* {duration}\n"
                f"*🎭 سبک:* {track.get('primaryGenreName', 'نامشخص')}\n"
                f"*📅 انتشار:* {release}\n")
        
        markup = [
            [InlineKeyboardButton("⬇️ دانلود", callback_data=f"download:{track_id}")],
            []
        ]
        
        if track.get('collectionId'):
            markup[1].append(InlineKeyboardButton("📀 آلبوم", callback_data=f"collection:{track['collectionId']}:1"))
        if track.get('artistId'):
            markup[1].append(InlineKeyboardButton("🎤 هنرمند", callback_data=f"artist:{track['artistId']}:1"))
        
        if track.get('previewUrl'):
            markup[0].append(InlineKeyboardButton("🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"))
        
        artwork = get_high_res_artwork(track.get("artworkUrl100"))
        await edit_or_send(bot, chat_id, msg_to_edit, text, markup, artwork, 'track', track_id, 
                          track.get('collectionId'), owner_id)
        await status.delete()
        
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"retry:track:{track_id}", status)

async def show_artist(chat_id: int, artist_id: int, page: int = 1, msg_to_edit: Message = None, owner_id: int = None):
    """Show artist page"""
    status = await send_message(bot, chat_id, "🔄 *در حال بارگذاری هنرمند...*")
    
    try:
        artist_data = await get_or_crawl_artist(artist_id, status)
        if not artist_data:
            await send_error_with_retry(bot, chat_id, "هنرمند یافت نشد.", f"retry:artist:{artist_id}", status)
            return
        
        artist = artist_data['results'][0]
        collections_data = await get_or_crawl_artist_collections(artist_id)
        collections = collections_data.get("results", []) if collections_data else []
        
        text = (f"*🎤 هنرمند:* {artist.get('artistName', 'نامشخص')}\n"
                f"*🎭 سبک:* {artist.get('primaryGenreName', 'نامشخص')}\n")
        
        # Paginate albums
        total = len(collections)
        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(1, min(page, total_pages))
        start = (page - 1) * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_albums = collections[start:end]
        
        if collections:
            text += f"\n*📀 آلبوم‌ها ({total}):*\n"
        
        markup = []
        for album in page_albums:
            if album.get('wrapperType') == 'collection':
                markup.append([InlineKeyboardButton(
                    f"📀 {album.get('collectionName', 'نامشخص')[:45]}",
                    callback_data=f"collection:{album['collectionId']}:1"
                )])
        
        if total_pages > 1:
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"artist:{artist_id}:{page-1}"))
            if page < total_pages:
                row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"artist:{artist_id}:{page+1}"))
            if row:
                markup.append(row)
        
        markup.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:artist:{artist_id}")])
        
        artist_img = get_artist_image(artist.get('artistName'))
        await edit_or_send(bot, chat_id, msg_to_edit, text, markup, artist_img, 'artist', artist_id, owner_id=owner_id)
        await status.delete()
        
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"retry:artist:{artist_id}", status)

# ============================================================================
# Search Functions
# ============================================================================
async def search_and_send(chat_id: int, user_id: int, search_type: str, term: str, 
                          original_msg: Message = None, owner_id: int = None):
    """Perform search and send results"""
    type_names = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}
    status = await send_message(bot, chat_id, f"🔍 *جستجوی {type_names.get(search_type, search_type)}: {term}...*")
    
    try:
        entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
        results = await search_itunes(term, entity=entity_map.get(search_type), limit=50)
        
        if results and results.get("resultCount", 0) > 0:
            await send_search_results(chat_id, search_type, term, results, 1, owner_id or user_id)
            await status.delete()
            await api_client.log_search(user_id, search_type, term, results.get("resultCount", 0))
        else:
            await send_error_with_retry(bot, chat_id, f"نتیجه‌ای برای '{term}' یافت نشد.",
                                       f"retry:search:{search_type}:{term}", status)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا: {str(e)[:100]}", f"retry:search:{search_type}:{term}", status)

async def send_search_results(chat_id: int, search_type: str, term: str, results: dict, page: int,
                             owner_id: int = None, msg_to_edit: Message = None):
    """Send paginated search results"""
    items = results["results"]
    total = len(items)
    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))
    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = items[start:end]
    
    type_names = {"artist": "هنرمند", "collection": "آلبوم", "track": "آهنگ"}
    header = f"📋 *نتایج {type_names.get(search_type, search_type)}: {term}*\nتعداد: {total} مورد"
    
    markup = []
    for item in page_items:
        wrapper = item.get("wrapperType")
        if wrapper == "artist":
            markup.append([InlineKeyboardButton(
                f"🎤 {item.get('artistName', 'نامشخص')}",
                callback_data=f"artist:{item['artistId']}:1"
            )])
        elif wrapper == "collection":
            markup.append([InlineKeyboardButton(
                f"📀 {item.get('collectionName', 'نامشخص')[:45]}",
                callback_data=f"collection:{item['collectionId']}:1"
            )])
        elif wrapper == "track":
            markup.append([InlineKeyboardButton(
                f"🎵 {item.get('trackName', 'نامشخص')[:45]}",
                callback_data=f"track:{item['trackId']}"
            )])
    
    if total_pages > 1:
        search_id = generate_search_hash(search_type, term)
        await cache_set(search_id, {"type": search_type, "term": term, "results": results, "owner": owner_id}, 
                       SEARCH_CACHE_TTL, "search")
        
        row = []
        if page > 1:
            row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"page:search:{search_id}:{search_type}:{page-1}"))
        if page < total_pages:
            row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"page:search:{search_id}:{search_type}:{page+1}"))
        if row:
            markup.append(row)
    
    # Refine buttons
    markup.append([
        InlineKeyboardButton("🔍 آلبوم‌ها", callback_data=f"refine:album:{term}"),
        InlineKeyboardButton("🔍 هنرمندان", callback_data=f"refine:artist:{term}"),
        InlineKeyboardButton("🔍 آهنگ‌ها", callback_data=f"refine:track:{term}")
    ])
    
    await edit_or_send(bot, chat_id, msg_to_edit, header, markup, owner_id=owner_id)

# ============================================================================
# Message Handlers
# ============================================================================
async def handle_start(message: Message):
    welcome = (f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
               f"فقط کافیه اسم آهنگ رو به انگلیسی بفرستید.\n\n"
               f"⚡ `/quick [نام آهنگ]` - دانلود خودکار اولین نتیجه\n"
               f"📀 دانلود آلبوم - از صفحه آلبوم\n"
               f"🔧 `/settings` - تنظیمات\n"
               f"📊 `/stats` - آمار شما")
    if INFO_CHANNEL_ID:
        welcome += f"\n\n📢 [کانال اطلاع‌رسانی](ble.ir/join/4T95Zt7P5X)"
    await reply_message(message, welcome)

async def handle_help(message: Message):
    help_text = (f"🛠 *راهنمای استفاده*\n\n"
                f"ارسال نام آهنگ (انگلیسی) - جستجو\n"
                f"`/quick [نام]` - دانلود خودکار\n"
                f"`/track [نام]` - جستجوی آهنگ\n"
                f"`/album [نام]` - جستجوی آلبوم\n"
                f"`/artist [نام]` - جستجوی هنرمند\n"
                f"`/settings` - تنظیم حالت سریع\n"
                f"`/stats` - آمار دانلود")
    await reply_message(message, help_text)

async def handle_settings(message: Message):
    user_id = message.author.id
    current = user_quick_mode.get(user_id, False)
    status = "✅ فعال" if current else "❌ غیرفعال"
    markup = [[InlineKeyboardButton("⚡ تغییر حالت سریع", callback_data="toggle_quick_mode")]]
    await reply_message(message, f"⚙️ *تنظیمات*\nحالت سریع: {status}", reply_markup=markup)

async def handle_stats(message: Message):
    user_id = message.author.id
    remaining = rate_limiter.users.get(user_id, [])
    dl_remaining = download_limiter.users.get(user_id, [])
    
    user_data = await api_client.get_user(user_id)
    searches = user_data.get('data', {}).get('total_searches', 0) if user_data.get('success') else 0
    downloads = user_data.get('data', {}).get('total_downloads', 0) if user_data.get('success') else 0
    
    await reply_message(message,
        f"📊 *آمار شما*\n\n"
        f"جستجوهای امروز: {len(remaining)}/30\n"
        f"دانلودهای امروز: {len(dl_remaining)}/100\n"
        f"حالت سریع: {'✅ فعال' if user_quick_mode.get(user_id, False) else '❌ غیرفعال'}\n\n"
        f"📈 مجموع:\nجستجو: {searches}\nدانلود: {downloads}")

# ============================================================================
# Bot Initialization
# ============================================================================
bot = Client(token=BOT_TOKEN)

@bot.on_initialize()
async def init():
    global HTTP_SESSION
    HTTP_SESSION = aiohttp.ClientSession()
    await api_client._request('get_required_channels', {})
    logger.info(f"Bot started - {BOT_NAME}")
    asyncio.create_task(cleanup_caches())

@bot.on_shutdown()
async def shutdown():
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()
    if api_client.session and not api_client.session.closed:
        await api_client.session.close()
    logger.info("Shutdown complete")

@bot.on_message()
async def on_message(message: Message):
    if message.author.is_bot:
        return
    
    await api_client.register_user({
        'user_id': message.author.id,
        'username': message.author.username or '',
        'first_name': message.author.first_name or '',
        'last_name': message.author.last_name or '',
    })
    
    # Handle channel broadcasts
    if message.chat.type == "channel":
        await process_broadcast_message(message)
        return
    
    msg_text = message.content or ""
    user_id = message.author.id
    chat_id = message.chat.id
    is_group = message.chat.type in ["group", "supergroup"]
    
    # Check membership for private chats
    if not is_group and not msg_text.startswith("/start"):
        is_member, _ = await verify_memberships(user_id)
        if not is_member:
            await reply_message(message, "⚠️ *لطفاً در کانال‌های مورد نیاز عضو شوید*")
            return
    
    # Group message handling
    if is_group:
        if f"@{bot.user.username}" not in msg_text:
            return
        msg_text = msg_text.replace(f"@{bot.user.username}", "").strip()
        if len(msg_text) > 100:
            await reply_message(message, "⚠️ متن پیام بیش از ۱۰۰ کاراکتر است")
            return
    
    # Commands
    if msg_text.startswith("/start"):
        await handle_start(message)
    elif msg_text.startswith("/help"):
        await handle_help(message)
    elif msg_text.startswith("/settings"):
        await handle_settings(message)
    elif msg_text.startswith("/stats"):
        await handle_stats(message)
    elif msg_text.startswith("/quick"):
        term = msg_text[6:].strip()
        if term:
            await quick_search_and_send(bot, chat_id, user_id, term, message)
    else:
        # Parse search query
        if msg_text.startswith("/track"):
            term = msg_text[6:].strip()
            if term:
                await search_and_send(chat_id, user_id, "track", term, message, user_id)
        elif msg_text.startswith("/album"):
            term = msg_text[6:].strip()
            if term:
                await search_and_send(chat_id, user_id, "album", term, message, user_id)
        elif msg_text.startswith("/artist"):
            term = msg_text[7:].strip()
            if term:
                await search_and_send(chat_id, user_id, "artist", term, message, user_id)
        elif msg_text and not msg_text.startswith("/"):
            if user_quick_mode.get(user_id, False):
                await quick_search_and_send(bot, chat_id, user_id, msg_text, message)
            else:
                await search_and_send(chat_id, user_id, "track", msg_text, message, user_id)

@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    callback = callback_query
    data = callback.data
    user_id = callback.author.id
    chat_id = callback.message.chat.id
    msg_id = callback.message.id
    is_group = callback.message.chat.type in ["group", "supergroup"]
    
    # Ownership check for groups
    if is_group:
        owner = MESSAGE_OWNER.get(msg_id)
        if owner and owner[0] != user_id:
            await bot.answer_callback_query(callback.id, "❌ این پیام متعلق به شما نیست", True)
            return
    
    if data == "toggle_quick_mode":
        current = user_quick_mode.get(user_id, False)
        user_quick_mode[user_id] = not current
        await api_client.update_quick_mode(user_id, not current)
        await bot.answer_callback_query(callback.id, f"⚡ حالت سریع {'فعال' if not current else 'غیرفعال'} شد", True)
        return
    
    if data.startswith("cancel_album:"):
        parts = data.split(":")
        if len(parts) >= 3:
            owner_id = int(parts[1])
            album_id = int(parts[2])
            if user_id == owner_id:
                album_tracker.cancel(owner_id, album_id)
                await bot.answer_callback_query(callback.id, "⏹️ لغو دانلود آلبوم...", True)
        return
    
    try:
        if data.startswith("artist:"):
            parts = data.split(":")
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist(chat_id, artist_id, page, callback.message, user_id)
            
        elif data.startswith("collection:"):
            parts = data.split(":")
            collection_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_album(chat_id, collection_id, page, callback.message, user_id)
            
        elif data.startswith("track:"):
            track_id = int(data.split(":")[1])
            await show_track(chat_id, track_id, callback.message, user_id)
            
        elif data.startswith("download:"):
            track_id = int(data.split(":")[1])
            can_dl, wait = await download_limiter.can_download(user_id)
            if not can_dl:
                await bot.answer_callback_query(callback.id, f"⏳ {wait} ثانیه صبر کنید", True)
                return
            await bot.answer_callback_query(callback.id, "🎵 در حال پردازش...")
            asyncio.create_task(download_track(bot, chat_id, track_id, user_id))
            
        elif data.startswith("download_album:"):
            album_id = int(data.split(":")[1])
            if is_group:
                await bot.answer_callback_query(callback.id, "❌ دانلود آلبوم در گروه مجاز نیست", True)
                return
            
            can_dl, wait = await download_limiter.can_download(user_id)
            if not can_dl:
                await bot.answer_callback_query(callback.id, f"⏳ {wait} ثانیه صبر کنید", True)
                return
            
            await bot.answer_callback_query(callback.id, "📀 آماده‌سازی آلبوم...")
            
            album_data = await get_or_crawl_collection(album_id)
            tracks_data = await get_or_crawl_collection_tracks(album_id)
            tracks = tracks_data.get("results", []) if tracks_data else []
            
            if not tracks:
                await bot.answer_callback_query(callback.id, "❌ آلبوم خالی است", True)
                return
            
            name = album_data['results'][0].get('collectionName', 'آلبوم') if album_data else 'آلبوم'
            status_msg = await send_message(bot, chat_id, f"🎵 *شروع دانلود آلبوم: {name}*")
            asyncio.create_task(download_album(bot, chat_id, album_id, user_id, name, tracks, status_msg))
            
        elif data.startswith("preview:"):
            track_id = int(data.split(":")[1])
            await bot.answer_callback_query(callback.id, "🎧 در حال دریافت پیش‌نمایش...")
            asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
            
        elif data.startswith("recrawl:"):
            parts = data.split(":")
            type_ = parts[1]
            id_ = int(parts[2])
            await bot.answer_callback_query(callback.id, "🔄 در حال بروزرسانی...")
            if type_ == "artist":
                await show_artist(chat_id, id_, 1, callback.message, user_id, force=True)
            elif type_ == "collection":
                await show_album(chat_id, id_, 1, callback.message, user_id, force=True)
                
        elif data.startswith("refine:"):
            parts = data.split(":")
            entity = parts[1]
            term = parts[2]
            await search_and_send(chat_id, user_id, entity, term, owner_id=user_id)
            
        elif data.startswith("page:search:"):
            parts = data.split(":")
            search_id = parts[2]
            search_type = parts[3]
            page = int(parts[4])
            cached = await cache_get(search_id, SEARCH_CACHE_TTL, "search")
            if cached:
                if is_group and cached.get("owner") != user_id:
                    await bot.answer_callback_query(callback.id, "❌ این جستجو متعلق به شما نیست", True)
                    return
                await send_search_results(chat_id, cached["type"], cached["term"], cached["results"], 
                                         page, cached.get("owner"), callback.message)
            else:
                await bot.answer_callback_query(callback.id, "⏳ نتایج منقضی شده، دوباره جستجو کنید", True)
                
        elif data.startswith("retry:"):
            retry_data = data[5:]
            await bot.answer_callback_query(callback.id, "🔄 تلاش مجدد...")
            if retry_data.startswith("search:"):
                _, type_, term = retry_data.split(":", 2)
                await search_and_send(chat_id, user_id, type_, term, owner_id=user_id)
            elif retry_data.startswith("download:"):
                _, track_id = retry_data.split(":")
                asyncio.create_task(download_track(bot, chat_id, int(track_id), user_id))
            elif retry_data.startswith("track:"):
                _, track_id = retry_data.split(":")
                await show_track(chat_id, int(track_id), callback.message, user_id)
            elif retry_data.startswith("album:"):
                _, album_id = retry_data.split(":")
                await show_album(chat_id, int(album_id), 1, callback.message, user_id)
            elif retry_data.startswith("artist:"):
                _, artist_id = retry_data.split(":")
                await show_artist(chat_id, int(artist_id), 1, callback.message, user_id)
            await callback.message.delete()
            
        await bot.answer_callback_query(callback.id)
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await bot.answer_callback_query(callback.id, f"❌ خطا: {str(e)[:50]}", True)

# ============================================================================
# Main Entry Point
# ============================================================================
async def cleanup_caches():
    """Background cache cleanup"""
    while True:
        await asyncio.sleep(3600)
        try:
            now = time.time()
            for cache_file in CACHE_DIR.glob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        data = pickle.load(f)
                    if now - data["timestamp"] > data.get("ttl", SEARCH_CACHE_TTL):
                        cache_file.unlink()
                except:
                    cache_file.unlink()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def signal_handler(signum, frame):
    logger.info(f"Signal {signum} received, shutting down...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    logger.info(f'"{BOT_NAME}" starting...')
    while True:
        try:
            bot.run()
        except KeyboardInterrupt:
            logger.info("Bot stopped")
            break
        except Exception as e:
            logger.exception(f"Bot crashed: {e}")
            logger.info("Restarting in 60 seconds...")
            time.sleep(60)