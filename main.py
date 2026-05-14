import logging
import asyncio
import hashlib
import os
import random
import time
import json
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

import aiohttp
import aiosqlite
from balethon import Client
from balethon.objects import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboard

from broadcast import broadcast_worker, handle_channel_post
from config import BOT_NAME, FOOTER, OFFLINE_MODE, ITEMS_PER_PAGE, BOT_TOKEN, DB_CHANNEL_ID, INFO_CHANNEL_ID, logger, \
    BROADCAST_CHANNELS, ITUNES_BASE_URL
from crawlers.itunes import search_itunes, lookup_itunes
from crawlers.utils import get_or_crawl_collection, \
    get_or_crawl_artist, get_track, get_or_crawl_collection_tracks, get_or_crawl_artist_collections
from crawlers.youtube import download_audio, search_youtube_track
from db.utils import insert_artist, get_search_cache, insert_search_cache, insert_collection, insert_track, init_db, \
    set_cache, get_cache, \
    get_collection_tracks, get_users_db, insert_user, local_search, get_artist_collections, get_all_users, \
    get_track_db, \
    get_collection_db, get_artist_db
from utils import tag_mp3
import requests
from typing import Optional, Dict, Any


def set_mirror(entity_type: str, entity_id: str, url_type: str, mirror_url: str) -> Dict[str, Any]:
    """
    POST /mirror/set
    Sets a mirror URL for a specific entity
    """
    url = f"{ITUNES_BASE_URL}/mirror/set"
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type,
        "mirror_url": mirror_url
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()


def get_mirror(entity_type: str, entity_id: str, url_type: str) -> Dict[str, Any]:
    """
    GET /mirror/get
    Retrieves a mirror URL for a specific entity
    """
    url = f"{ITUNES_BASE_URL}/mirror/get"
    params = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def delete_mirror(entity_type: str, entity_id: str, url_type: str, method: str = "POST") -> Dict[str, Any]:
    """
    DELETE or POST /mirror/delete
    Deletes a mirror URL for a specific entity
    method: Either "POST" or "DELETE" (default: "POST")
    """
    url = f"{ITUNES_BASE_URL}/mirror/delete"
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url_type": url_type
    }

    if method.upper() == "DELETE":
        response = requests.delete(url, json=payload)
    else:  # Default to POST
        response = requests.post(url, json=payload)

    response.raise_for_status()
    return response.json()


from typing import Optional, Dict, Any


class MirrorAPI:
    def __init__(self, base_url: str = "https://3rah.ir/music/mirror/"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()

    def set_mirror(self, entity_type: str, entity_id: str, url_type: str, mirror_url: str) -> Dict[str, Any]:
        """POST /mirror/set - Set a mirror URL"""
        url = f"{self.base_url}/mirror/set"
        payload = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "url_type": url_type,
            "mirror_url": mirror_url
        }
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def get_mirror(self, entity_type: str, entity_id: str, url_type: str) -> Dict[str, Any]:
        """GET /mirror/get - Get a mirror URL"""
        url = f"{self.base_url}/mirror/get"
        params = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "url_type": url_type
        }
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def delete_mirror(self, entity_type: str, entity_id: str, url_type: str, use_delete_method: bool = False) -> Dict[
        str, Any]:
        """Delete a mirror URL - uses POST by default or DELETE if specified"""
        url = f"{self.base_url}/mirror/delete"
        payload = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "url_type": url_type
        }

        if use_delete_method:
            response = self.session.delete(url, json=payload)
        else:
            response = self.session.post(url, json=payload)

        response.raise_for_status()
        return response.json()


# ============================================================================
# HTTP Session & Semaphores
# ============================================================================
HTTP_SESSION: Optional[aiohttp.ClientSession] = None
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(20)

# ============================================================================
# File-based Cache System
# ============================================================================
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

# Cache TTLs
SEARCH_CACHE_TTL = 600  # 10 minutes
ARTWORK_CACHE_TTL = 86400  # 24 hours
PREVIEW_CACHE_TTL = 86400  # 24 hours
TRACK_CACHE_TTL = 604800  # 7 days


def get_cache_file_path(cache_key: str) -> Path:
    """Get file path for a cache key"""
    # Use MD5 to create a safe filename
    safe_name = hashlib.md5(cache_key.encode()).hexdigest()
    return CACHE_DIR / f"{safe_name}.cache"


async def save_to_file_cache(cache_key: str, data: Any, ttl: int = SEARCH_CACHE_TTL):
    """Save data to file cache with TTL"""
    try:
        cache_path = get_cache_file_path(cache_key)
        cache_data = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl
        }
        # Use pickle for complex objects
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_data, f)
        return True
    except Exception as e:
        logger.error(f"Failed to save to file cache {cache_key}: {e}")
        return False


async def get_from_file_cache(cache_key: str) -> Optional[Any]:
    """Get data from file cache if not expired"""
    try:
        cache_path = get_cache_file_path(cache_key)
        if not cache_path.exists():
            return None

        with open(cache_path, 'rb') as f:
            cache_data = pickle.load(f)

        # Check if expired
        if time.time() - cache_data["timestamp"] > cache_data["ttl"]:
            cache_path.unlink(missing_ok=True)
            return None

        return cache_data["data"]
    except Exception as e:
        logger.error(f"Failed to read from file cache {cache_key}: {e}")
        return None


async def clear_expired_cache():
    """Clear all expired cache files"""
    while True:
        await asyncio.sleep(3600)  # every hour
        try:
            now = time.time()
            for cache_file in CACHE_DIR.glob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                    if now - cache_data["timestamp"] > cache_data["ttl"]:
                        cache_file.unlink()
                except:
                    cache_file.unlink()  # Remove corrupted files
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")


# In-memory search cache (still needed for active sessions)
SEARCH_CACHE = {}
SEARCH_CACHE_MAX_ITEMS = 100

# Message ownership mapping for group interactions
# { message_id: (owner_user_id, timestamp) }
MESSAGE_OWNER = {}
MESSAGE_OWNER_TTL = 600  # 10 minutes

# ============================================================================
# Retry Button Helper
# ============================================================================
close_btn = InlineKeyboard([InlineKeyboardButton(text="❌ بستن", callback_data="close")])


def create_retry_button(callback_data: str, button_text: str = "🔄 تلاش مجدد") -> InlineKeyboardButton:
    """Create a retry button for error messages"""
    return InlineKeyboardButton(text=button_text, callback_data=f"retry:{callback_data}")


async def send_error_with_retry(bot: Client, chat_id: int, error_text: str, retry_callback: str,
                                original_message: Optional[Message] = None):
    """Send an error message with retry button"""
    markup = InlineKeyboard([
        [create_retry_button(retry_callback)],
        [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
    ])

    if original_message:
        try:
            await original_message.edit(f"❌ *خطا:* {error_text}{FOOTER}", reply_markup=markup)
        except:
            await bot.send_message(chat_id, f"❌ *خطا:* {error_text}{FOOTER}", reply_markup=markup)
    else:
        await bot.send_message(chat_id, f"❌ *خطا:* {error_text}{FOOTER}", reply_markup=markup)


async def update_status_with_close(status_msg: Message, text: str):
    """Update status message with close button"""
    try:
        await status_msg.edit(text, reply_markup=close_btn)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")


# ============================================================================
# Periodic cleanup tasks
# ============================================================================
async def cleanup_caches():
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        now = time.time()
        # Clean search cache
        expired = [sid for sid, data in SEARCH_CACHE.items() if now - data["timestamp"] > SEARCH_CACHE_TTL]
        for sid in expired:
            SEARCH_CACHE.pop(sid, None)
        # Clean message owner mapping
        expired_msgs = [mid for mid, (_, ts) in MESSAGE_OWNER.items() if now - ts > MESSAGE_OWNER_TTL]
        for mid in expired_msgs:
            MESSAGE_OWNER.pop(mid, None)


async def store_search_cache(search_id: str, type_: str, term: str, results: dict, owner_id: int):
    """Store search results in memory with TTL"""
    # Limit cache size
    if len(SEARCH_CACHE) >= SEARCH_CACHE_MAX_ITEMS:
        # Remove oldest entry
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
    """Retrieve search results from memory, check TTL"""
    data = SEARCH_CACHE.get(search_id)
    if data and time.time() - data["timestamp"] <= SEARCH_CACHE_TTL:
        return data
    if data:
        SEARCH_CACHE.pop(search_id, None)
    return None


def set_message_owner(message_id: int, owner_id: int):
    """Store which user owns this message (for group interactions)"""
    MESSAGE_OWNER[message_id] = (owner_id, time.time())


def get_message_owner(message_id: int) -> Optional[int]:
    """Get owner of a message, if any"""
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

# ============================================================================
# User State Management
# ============================================================================
user_states = {}
user_last_message = {}
user_quick_mode = {}  # Stores quick mode preference per user

# ============================================================================
# Logging
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logging.getLogger("balethon").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("ytmusicapi").setLevel(logging.WARNING)
logger.setLevel(logging.INFO)
if OFFLINE_MODE:
    logger.warning("Bot running in OFFLINE MODE – no external API calls will be made.")


# ============================================================================
# Helper Functions
# ============================================================================
def format_duration(milliseconds: int) -> str:
    if not milliseconds:
        return "نامشخص"
    minutes = milliseconds // 60000
    seconds = (milliseconds % 60000) // 1000
    return f"{minutes}:{seconds:02d}"


def get_high_res_artwork(url: str, size: int = 600) -> str:
    if not url:
        return ""
    return url.replace("100x100bb", f"{size}x{size}bb")


def create_pagination_row(callback_prefix: str, current_page: int, total_pages: int) -> List[InlineKeyboardButton]:
    row = []
    if current_page > 1:
        row.append(InlineKeyboardButton(text="▶️ قبلی", callback_data=f"{callback_prefix}:{current_page - 1}"))
    row.append(InlineKeyboardButton(text=f"صفحه {current_page} از {total_pages}", callback_data="ignore"))
    if current_page < total_pages:
        row.append(InlineKeyboardButton(text="بعدی ◀️", callback_data=f"{callback_prefix}:{current_page + 1}"))
    return row


def generate_search_hash(type_: str, term: str) -> str:
    return hashlib.md5(f"{type_}:{term}:{time.time()}".encode()).hexdigest()[:10]  # include time to avoid collisions


async def edit_or_send(bot: Client, chat_id: int, message_to_edit: Optional[Message], text: str,
                       markup, artwork_url: str = None, cache_id=None, owner_id=None):
    """Send a new message or edit an existing one, and store message owner for groups."""
    if artwork_url:
        artwork_cache = None
        if cache_id:
            data = get_mirror('collection', cache_id, 'artworkUrl')
            logger.info(data["mirrors"])
            if len(data["mirrors"]) > 0:
                artwork_cache = data["mirrors"][0]
                for mirror in data["mirrors"]:
                    if 'mirror_url' in mirror:
                        artwork_cache = mirror["mirror_url"].split('<token>/')[1]
            if artwork_cache:
                artwork_url = artwork_cache
        try:
            msg = await bot.send_photo(chat_id, photo=artwork_url, caption=text, reply_markup=markup)
            if cache_id and not artwork_cache and msg:
                set_mirror('collection', cache_id, 'artworkUrl',
                           'https://tapi.bale.ai/file/bot<token>/' + str(msg.photo[0].id))
        except Exception as e:
            msg = await bot.send_message(chat_id, text=text, reply_markup=markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=markup)

    # Store owner for the new message
    if owner_id and msg and msg.chat.type in ["group", "supergroup"]:
        set_message_owner(msg.id, owner_id)

    if message_to_edit:
        try:
            # Remove owner mapping for old message if exists
            if message_to_edit.id in MESSAGE_OWNER:
                MESSAGE_OWNER.pop(message_to_edit.id, None)
            await message_to_edit.delete()
        except:
            pass

    return msg


def _get_file_size_sync(path_str):
    p = Path(path_str)
    return p.stat().st_size / (1024 * 1024) if p.exists() else 0


def _delete_file_sync(path_str):
    try:
        p = Path(path_str)
        if p.exists():
            p.unlink()
    except Exception as e:
        logger.error(f"Failed to delete temp file {path_str}: {e}")


# ============================================================================
# Quick Mode - Auto select first track result
# ============================================================================
async def quick_search_and_send(bot: Client, chat_id: int, user_id: int, term: str, original_message: Message = None):
    """Search for track and automatically send the first result"""
    status_msg = await bot.send_message(chat_id, f"⚡ *حالت سریع: جستجوی {term}...*{FOOTER}", reply_markup=close_btn)

    try:
        results = await search_itunes(term, entity="musicTrack", limit=1)

        if results and results.get("resultCount", 0) > 0:
            track = results["results"][0]
            track_id = track.get('trackId')
            if track_id:
                await show_track(chat_id, track_id, original_message, user_id)
                await status_msg.delete()
            else:
                await send_error_with_retry(bot, chat_id, f"نتیجه‌ای برای '{term}' یافت نشد.",
                                            f"quick_retry:{term}", status_msg)
        else:
            await send_error_with_retry(bot, chat_id, f"نتیجه‌ای برای '{term}' یافت نشد.",
                                        f"quick_retry:{term}", status_msg)
    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در جستجو: {str(e)[:100]}",
                                    f"quick_retry:{term}", status_msg)


# ============================================================================
# Download & Caching Logic
# ============================================================================
async def send_audio_with_retry(bot: Client, chat_id: int, audio_path: str, file_name: str, caption: str,
                                max_retries=3, direct=False, cache_id=None):
    last_exception = None
    abs_audio_path = os.path.abspath(str(audio_path))

    exists = await asyncio.to_thread(os.path.exists, abs_audio_path)
    if not exists:
        logger.error(f"File not found for upload: {abs_audio_path}")
        raise FileNotFoundError(f"File not found: {abs_audio_path}")

    chat_to_send = DB_CHANNEL_ID
    logger.info(f"Sending audio: {abs_audio_path} to chat {chat_to_send}")

    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_audio_path, 'rb') as audio_file:
                logger.info('Sending audio...')
                msg = await bot.send_audio(
                    chat_id=int(chat_id),
                    audio=audio_file,
                    caption=caption
                )

                set_mirror('track', str(cache_id), 'audioUrl',
                           'https://tapi.bale.ai/file/bot<token>/' + str(msg.audio.id))
                return msg

        except Exception as e:
            error_str = str(e)
            if "504" in error_str or "500" in error_str or "Time-out" in error_str:
                await bot.send_message(
                    chat_id=int(chat_to_send),
                    text="در حال حاضر سرور های بله برای آپلود پاسخگو نیستند",
                    reply_markup=close_btn
                )
                logger.warning(f"send_audio network/server error, retry {attempt}/{max_retries}: {e}")
                last_exception = e
                await asyncio.sleep(attempt * 2)
            else:
                logger.error(f"Upload failed fatally: {e}")
                raise e
    raise last_exception


async def send_cached_or_download(bot: Client, chat_id: int, track_id: int, user_id: int = None, caption=""):
    status_msg = await bot.send_message(chat_id, text=f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*{FOOTER}",
                                        reply_markup=close_btn)
    audio_cache = None
    audio_url = None
    if track_id:
        data = get_mirror('track', str(track_id), 'audioUrl')
        logger.info(data["mirrors"])
        if len(data["mirrors"]) > 0:
            audio_cache = data["mirrors"][0]
            for mirror in data["mirrors"]:
                if 'mirror_url' in mirror:
                    audio_cache = mirror["mirror_url"].split('<token>/')[1]
        if audio_cache:
            audio_url = audio_cache

    if audio_url and DB_CHANNEL_ID:
        try:
            await update_status_with_close(status_msg, f"📤 *در حال ارسال فایل از حافظه کش...*{FOOTER}")
            msg = await bot.send_audio(chat_id, audio=audio_url, caption=caption)
            await status_msg.delete()
            return
        except Exception as e:
            logger.error(f"Forward failed: {e}, will re-download")

    if OFFLINE_MODE:
        await send_error_with_retry(bot, chat_id, f"آهنگ در دیتابیس محلی یافت نشد و بات در حالت آفلاین است.",
                                    f"download_retry:{track_id}", status_msg)
        return

    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await send_error_with_retry(bot, chat_id, f"خطا در دریافت اطلاعات آهنگ.",
                                    f"download_retry:{track_id}", status_msg)
        return

    track = track_data["results"][0]
    t_name = track.get("trackName", "Unknown Title")
    ye = track.get("releaseDate", "").split("-")[0]
    a_name = track.get("artistName", "Unknown Artist")
    collection_name = track.get("collectionName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100", track.get("artworkUrl")), size=600)

    query = f'"{t_name}" by {a_name} collection {collection_name} {ye}'
    await update_status_with_close(status_msg, f"🔍 *جستجوی سورس باکیفیت آهنگ در یوتیوب موزیک...*{FOOTER}")

    try:
        video_id = await search_youtube_track(query)
        if not video_id:
            await send_error_with_retry(bot, chat_id, f"نتوانستیم لینک یوتیوب موزیک را برای این آهنگ پیدا کنیم.",
                                        f"download_retry:{track_id}", status_msg)
            return
        video_url = f"https://music.youtube.com/watch?v={video_id}"

        await update_status_with_close(status_msg, f"⏳ *در صف دانلود و آماده‌سازی...*{FOOTER}")

        mp3_path_str = None
        try:
            async with DOWNLOAD_SEMAPHORE:
                await update_status_with_close(status_msg,
                                               f"⏳ *در حال دانلود و پردازش (روش‌های پیشرفته ضدتحریم)...*{FOOTER}")
                mp3_path_str = await asyncio.get_event_loop().run_in_executor(
                    None, download_audio, video_url
                )

                if not mp3_path_str:
                    await send_error_with_retry(bot, chat_id, f"دانلود با شکست مواجه شد — همه ۸ روش ناموفق بودند.",
                                                f"download_retry:{track_id}", status_msg)
                    return

                file_size_mb = await asyncio.to_thread(_get_file_size_sync, mp3_path_str)
                if file_size_mb == 0:
                    await send_error_with_retry(bot, chat_id, f"خطای داخلی: فایل دانلود شده یافت نشد.",
                                                f"download_retry:{track_id}", status_msg)
                    return

                cover_bytes = None
                if cover_url and HTTP_SESSION:
                    try:
                        async with HTTP_SESSION.get(cover_url) as resp:
                            if resp.status == 200:
                                cover_bytes = await resp.read()
                    except Exception as e:
                        logger.error(f"Failed to download cover: {e}")

                await asyncio.get_event_loop().run_in_executor(
                    None, tag_mp3, mp3_path_str, track, cover_bytes
                )

                release_year = track.get("releaseDate", "").split("-")[0] if track.get("releaseDate") else ""

                caption_parts = [
                    f"🎵 آهنگ: {track.get('trackName', 'Unknown Title')}",
                    f"🎤 هنرمند: {track.get('artistName', 'Unknown Artist')}",
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
                    duration_sec = track['trackTimeMillis'] // 1000
                    minutes = duration_sec // 60
                    seconds = duration_sec % 60
                    caption_parts.append(f"⏱️ مدت زمان: {minutes}:{seconds:02d}")

                caption_parts.append(f"🔊 حجم فایل: {file_size_mb:.1f} MB{FOOTER}")
                caption = "\n".join(caption_parts)

                if DB_CHANNEL_ID:
                    try:
                        await update_status_with_close(status_msg,
                                                       f"☁️ *در حال آپلود در سرورهای ابری {BOT_NAME}...*{FOOTER}")
                        db_msg = await send_audio_with_retry(
                            bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption, cache_id=str(track['trackId'])
                        )
                    except Exception as e:
                        logger.error(f"Error caching to DB_CHANNEL: {e}")
                        msg = await send_audio_with_retry(bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption,
                                                          cache_id=str(track['trackId']))
                        await update_status_with_close(status_msg, f"✅ *آهنگ مستقیما ارسال شد.*{FOOTER}")
                else:
                    msg = await send_audio_with_retry(bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption,
                                                      cache_id=str(track['trackId']))
                    await update_status_with_close(status_msg, f"✅ *دانلود و ارسال با موفقیت انجام شد.*{FOOTER}")

                await status_msg.delete()

        except Exception as e:
            logger.exception("Download error")
            await send_error_with_retry(bot, chat_id, f"خطا در عملیات: {str(e)[:100]}",
                                        f"download_retry:{track_id}", status_msg)
        finally:
            if mp3_path_str:
                await asyncio.to_thread(_delete_file_sync, mp3_path_str)

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در جستجوی یوتیوب: {str(e)[:100]}",
                                    f"download_retry:{track_id}", status_msg)


async def send_voice_preview(bot: Client, chat_id: int, track_id: int, user_id: int = None):
    status_msg = await bot.send_message(chat_id, f"⏳ *در حال دریافت پیش‌نمایش...*{FOOTER}",
                                        reply_markup=close_btn)

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
            data = get_mirror('track', cache_id, 'previewUrl')
            logger.info(data["mirrors"])
            if len(data["mirrors"]) > 0:
                preview_cache = data["mirrors"][0]
                for mirror in data["mirrors"]:
                    if 'mirror_url' in mirror:
                        preview_cache = mirror["mirror_url"].split('<token>/')[1]
            if preview_cache:
                preview_url = preview_cache

        msg = await bot.send_voice(chat_id, voice=preview_url,
                                   caption=f"🎧 *پیش‌نمایش صوتی آهنگ {track.get('trackName')}*{FOOTER}")
        if msg and not preview_cache:
            set_mirror('track', str(track_id), 'previewUrl',
                       'https://tapi.bale.ai/file/bot<token>/' + str(msg.voice.id))
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Failed to send audio preview: {e}")
        await send_error_with_retry(bot, chat_id, f"خطا در ارسال پیش‌نمایش: {str(e)[:100]}",
                                    f"preview_retry:{track_id}", status_msg)


# ============================================================================
# Channel Membership Check
# ============================================================================
async def check_channel_membership(bot: Client, user_id: int) -> bool:
    is_registered = await get_users_db(user_id)
    if not is_registered:
        await insert_user(user_id)

    if not INFO_CHANNEL_ID:
        return True

    try:
        member = await bot.get_chat_member(int(INFO_CHANNEL_ID), user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id}: {e}")
        return False


async def require_membership(bot: Client, chat_id: int, user_id: int) -> bool:
    is_member = await check_channel_membership(bot, user_id)
    if not is_member:
        markup = InlineKeyboard(*[
            [InlineKeyboardButton(text="🔗 عضویت در کانال", url=f"https://ble.ir/abraava")],
            [InlineKeyboardButton(text="✅ تایید عضویت", callback_data="verify_membership")],
            [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
        ])
        await bot.send_message(
            chat_id,
            f"⚠️ *برای استفاده از {BOT_NAME}، ابتدا باید در کانال ما عضو شوید.*\n\n"
            f"پس از عضویت، روی دکمه «تایید عضویت» کلیک کنید.{FOOTER}",
            reply_markup=markup
        )
        return False
    return True


# ============================================================================
# Group Message Validation
# ============================================================================
def is_valid_message(message) -> bool:
    """Check if group message is valid for processing"""
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


# ============================================================================
# Bale Bot Initialization & Handlers
# ============================================================================
bot = Client(token=BOT_TOKEN)


@bot.on_initialize()
async def on_initialize():
    global HTTP_SESSION
    HTTP_SESSION = aiohttp.ClientSession()
    await init_db()
    logger.info("Database initialized successfully (relational tables ready).")
    logger.info(f"Bot started with rate limiting: {rate_limiter.max_requests} req/min per user")
    asyncio.create_task(broadcast_worker(bot))
    asyncio.create_task(cleanup_caches())
    asyncio.create_task(clear_expired_cache())


@bot.on_disconnect()
async def on_disconnect():
    global HTTP_SESSION
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()


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


@bot.on_message()
async def handle_message(message):
    if "abraava" in str(message.author.username):
        return
    if message.content:
        if message.chat.id in BROADCAST_CHANNELS and message.chat.type == "channel":
            await handle_channel_post(message)
            return

    is_group = message.chat.type in ["group", "supergroup", "channel"]
    msg_text = message.content or ""
    user_id = message.author.id
    chat_id = message.chat.id

    allowed, wait_time = await rate_limiter.check_user(user_id)
    if not allowed:
        if is_group:
            return
        await message.reply(
            f"⚠️ *محدودیت نرخ درخواست*\n\n"
            f"شما حداکثر {rate_limiter.max_requests} درخواست در دقیقه مجاز هستید.\n"
            f"لطفاً {wait_time} ثانیه صبر کنید.{FOOTER}",
            reply_markup=close_btn
        )
        return

    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention not in msg_text:
            return

        if not is_valid_message(message):
            return

        msg_text = msg_text.replace(bot_mention, "").strip()

        if len(msg_text) > 100:
            await message.reply(f"⚠️ *متن پیام خیلی طولانی است*\n\n"
                                f"حداکثر ۱۰۰ کاراکتر مجاز است.{FOOTER}",
                                reply_markup=close_btn)
            return
    else:
        if not is_valid_message(message):
            await message.reply(f"⚠️ *فرمت پیام نامعتبر*\n\n"
                                f"فقط پیام‌های متنی زیر ۱۰۰ کاراکتر قابل پردازش هستند.\n"
                                f"لطفاً بدون عکس، ویدیو، فایل و فوروارد پیام دهید.{FOOTER}",
                                reply_markup=close_btn)
            return

    if not is_group and INFO_CHANNEL_ID and not msg_text.startswith('/start'):
        is_member = await check_channel_membership(bot, user_id)
        if not is_member:
            await require_membership(bot, chat_id, user_id)
            return

    if msg_text.startswith("/start"):
        welcome_text = (
            f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
            f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n"
            f"فقط کافیه اسم آهنگ رو بگی، خودم بلدم چیکار کنم 😉\n\n"
            f"⚡ *حالت سریع:* برای دانلود خودکار اولین نتیجه، از `/quick [نام آهنگ]` استفاده کنید.\n"
            f"🔧 *تنظیمات:* برای فعال/غیرفعال کردن حالت سریع از `/settings` استفاده کنید."
        )
        if INFO_CHANNEL_ID:
            welcome_text += f"\n\n📢 *برای اطلاع از آخرین اخبار در کانال ما عضو شوید:* \n\nble.ir/join/4T95Zt7P5X"

        welcome_text += FOOTER

        markup = InlineKeyboard([
            [InlineKeyboardButton(text="📢 کانال اطلاع‌رسانی", url=f"ble.ir/join/4T95Zt7P5X")],
            [InlineKeyboardButton(text="⚡ حالت سریع", callback_data="toggle_quick_mode")],
            [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
        ])

        await message.reply(welcome_text, reply_markup=markup)

    elif msg_text.startswith("/help"):
        await message.reply(
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            "برای جستجوی موزیک کافیست نام آن را (به انگلیسی) بنویسید یا از دستور /search استفاده کنید.\n"
            "مثال: `Mohsen Namjoo`\n\n"
            "⚡ *حالت سریع:*\n"
            "`/quick نام آهنگ` - به صورت خودکار اولین نتیجه را دانلود می‌کند\n\n"
            "🎵 *دستورات اختصاصی:*\n"
            "`/track نام آهنگ` - جستجوی دقیق آهنگ\n"
            "`/album نام آلبوم` - جستجوی آلبوم\n"
            "`/artist نام هنرمند` - جستجوی هنرمند\n\n"
            "⚠️ اگر می‌خواهید ربات را در گروه‌ها استفاده کنید، حتما باید آیدی ربات را تگ کنید:\n"
            f"@{bot.user.username} Mohsen Namjoo\n\n"
            f"📝 *نکات گروه:*\n"
            f"• فقط پیام‌های متنی زیر ۱۰۰ کاراکتر پردازش می‌شوند\n"
            f"• بدون عکس، ویدیو، فایل یا پیام فوروارد شده\n"
            f"• فقط کاربری که ربات را صدا زده می‌تواند روی دکمه‌ها کلیک کند\n\n"
            f"🔒 محدودیت: {rate_limiter.max_requests} درخواست در دقیقه"
            f"{FOOTER}",
            reply_markup=close_btn
        )

    elif msg_text.startswith("/about"):
        await message.reply(
            f"ℹ️ *درباره ربات {BOT_NAME}*\n\n"
            f"این ربات یک دستیار هوشمند برای جستجو در دیتابیس عظیم iTunes و دانلود باکیفیت‌ترین سورس موجود از YouTube Music به صورت ضدتحریم می‌باشد.\n"
            f"تمامی آهنگ‌ها پیش از ارسال توسط سرورهای ما پردازش و تگ‌گذاری (کاور و اطلاعات) می‌شوند.\n\n"
            f"⚡ *حالت سریع:* دانلود خودکار اولین نتیجه جستجو\n\n"
            f"🔒 *Rate Limit:* {rate_limiter.max_requests} req/min per user"
            f"{FOOTER}",
            reply_markup=close_btn
        )

    elif msg_text.startswith("/settings"):
        current_mode = user_quick_mode.get(user_id, False)
        mode_status = "✅ فعال" if current_mode else "❌ غیرفعال"
        markup = InlineKeyboard([
            [InlineKeyboardButton(text="⚡ تغییر حالت سریع", callback_data="toggle_quick_mode")],
            [InlineKeyboardButton(text="❌ بستن", callback_data="close")]
        ])
        await message.reply(
            f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
            f"• حالت سریع: {mode_status}\n"
            f"• در حالت سریع، با ارسال نام آهنگ به صورت خودکار اولین نتیجه دانلود می‌شود.\n\n"
            f"برای فعال/غیرفعال کردن روی دکمه زیر کلیک کنید.{FOOTER}",
            reply_markup=markup
        )

    elif msg_text.startswith("/stats"):
        remaining = rate_limiter.get_user_remaining(user_id)
        quick_mode = user_quick_mode.get(user_id, False)
        await message.reply(
            f"📊 *آمار شما*\n\n"
            f"• درخواست‌های باقی‌مانده: {remaining}/{rate_limiter.max_requests}\n"
            f"• پنجره زمانی: {rate_limiter.time_window} ثانیه\n"
            f"• حالت سریع: {'✅ فعال' if quick_mode else '❌ غیرفعال'}\n"
            f"• وضعیت: {'✅ فعال' if remaining > 0 else '⛔ محدود شده'}"
            f"{FOOTER}",
            reply_markup=close_btn
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
# Search Handler (in-memory pagination, no DB for search cache)
# ============================================================================
async def handle_search_command(chat_id: int, user_id: int, type_: str, term: str, original_message: Message = None,
                                owner_id: int = None):
    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "quick": "سریع"}

    status_msg = await bot.send_message(chat_id,
                                        f"🔍 *در حال جستجوی {type_fa_map.get(type_)}: {term}...*{FOOTER}",
                                        reply_markup=close_btn)

    try:
        results = {}
        if not OFFLINE_MODE:
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            entity = entity_map.get(type_) if type_ != "all" else None
            itunes_results = await search_itunes(term, entity=entity, limit=50)
            if itunes_results and itunes_results.get("resultCount", 0) > 0:
                results = itunes_results
                for item in results["results"]:
                    if item.get("wrapperType") == "artist":
                        await insert_artist(item)
                    elif item.get("wrapperType") == "collection":
                        await insert_collection(item)
                    elif item.get("wrapperType") == "track":
                        await insert_track(item)
        else:
            results = await local_search(term, type_)

        if results and results.get("resultCount", 0) > 0:
            await send_search_page(chat_id, type_, term, results, 1, original_term=term, owner_id=owner_id or user_id)
            await status_msg.delete()
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
    markup.append([InlineKeyboardButton("🔍 آلبوم‌ها", f"refine:collection:{refine_term}"),
                   InlineKeyboardButton("🔍 هنرمندان", f"refine:artist:{refine_term}"),
                   InlineKeyboardButton("🔍 آهنگ‌ها", f"refine:track:{refine_term}")])

    markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

    text = header + FOOTER

    msg = await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), owner_id=owner_id)


# ============================================================================
# Callback Handler with Ownership Check
# ============================================================================
@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id
    message_id = callback_query.message.id
    is_group = callback_query.message.chat.type in ["group", "supergroup"]

    if is_group:
        owner = get_message_owner(message_id)
        if owner is not None and owner != user_id:
            await bot.answer_callback_query(callback_query.id, "❌ شما اجازه تعامل با این پیام را ندارید.",
                                            show_alert=True)
            return

    allowed, wait_time = await rate_limiter.check_user(user_id)
    if not allowed:
        await bot.answer_callback_query(callback_query.id, f"⏳ لطفاً {wait_time} ثانیه صبر کنید", show_alert=True)
        return

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
    if data == "verify_membership":
        if INFO_CHANNEL_ID:
            is_member = await check_channel_membership(bot, user_id)
            if is_member:
                await bot.answer_callback_query(callback_query.id, "✅ عضویت شما تایید شد!", show_alert=True)
                await bot.send_message(
                    chat_id,
                    f"✅ *عضویت شما با موفقیت تایید شد!*\n\n"
                    f"حالا می‌توانید از {BOT_NAME} استفاده کنید.\n"
                    f"کافیست نام آهنگ مورد نظر خود را بنویسید.{FOOTER}",
                    reply_markup=close_btn
                )
                await callback_query.message.delete()
            else:
                await bot.answer_callback_query(callback_query.id, "❌ هنوز عضو نشده‌اید!", show_alert=True)
        return
    if data == "toggle_quick_mode":
        current = user_quick_mode.get(user_id, False)
        user_quick_mode[user_id] = not current
        status = "فعال" if not current else "غیرفعال"
        await bot.answer_callback_query(callback_query.id, f"⚡ حالت سریع {status} شد!", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=close_btn)
        return

    # Handle retry callbacks
    if data.startswith("retry:"):
        retry_data = data[6:]  # Remove "retry:" prefix
        await bot.answer_callback_query(callback_query.id, "🔄 در حال تلاش مجدد...")

        if retry_data.startswith("search_retry:"):
            _, type_, term = retry_data.split(":", 2)
            await handle_search_command(chat_id, user_id, type_, term, owner_id=user_id)
        elif retry_data.startswith("download_retry:"):
            _, track_id = retry_data.split(":")
            asyncio.create_task(send_cached_or_download(bot, chat_id, int(track_id), user_id))
        elif retry_data.startswith("preview_retry:"):
            _, track_id = retry_data.split(":")
            asyncio.create_task(send_voice_preview(bot, chat_id, int(track_id), user_id))
        elif retry_data.startswith("quick_retry:"):
            _, term = retry_data.split(":", 1)
            await quick_search_and_send(bot, chat_id, user_id, term)

        # Delete the error message after retry
        try:
            await callback_query.message.delete()
        except:
            pass
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
                    await bot.answer_callback_query(callback_query.id, "❌ این جستجو متعلق به شما نیست.",
                                                    show_alert=True)
                    return
                await send_search_page(chat_id, cached["type"], cached["term"], cached["results"], page,
                                       callback_query.message, owner_id=cached["owner_id"])
            else:
                await bot.answer_callback_query(callback_query.id,
                                                "⏳ نتایج جستجو منقضی شده‌اند. لطفاً دوباره جستجو کنید.",
                                                show_alert=True)
        elif data.startswith("refine:"):
            entity = parts[1]
            term = parts[2]
            await handle_search_command(chat_id, user_id, entity, term, owner_id=user_id)
        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist(chat_id, artist_id, page, callback_query.message, user_id)
        elif data.startswith("collection:"):
            collection_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_collection(chat_id, collection_id, page, callback_query.message, user_id)
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track(chat_id, track_id, callback_query.message, user_id)
        elif data.startswith("download:"):
            track_id = int(parts[1])
            await bot.answer_callback_query(callback_query.id, "در حال پردازش دانلود...")
            asyncio.create_task(send_cached_or_download(bot, chat_id, track_id, user_id))
        elif data.startswith("preview:"):
            track_id = int(parts[1])
            await bot.answer_callback_query(callback_query.id, "در حال دریافت پیش‌نمایش...")
            asyncio.create_task(send_voice_preview(bot, chat_id, track_id, user_id))
        elif data.startswith("recrawl:"):
            type_ = parts[1]
            id_ = int(parts[2])
            await bot.answer_callback_query(callback_query.id, "در حال بروزرسانی اطلاعات...")
            if type_ == "artist":
                await show_artist(chat_id, id_, 1, callback_query.message, user_id, force=True)
            elif type_ == "collection":
                await show_collection(chat_id, id_, 1, callback_query.message, user_id, force=True)

    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")
        await bot.answer_callback_query(callback_query.id, f"❌ خطا: {str(e)[:50]}", show_alert=True)


# ============================================================================
# Show Functions (using relational DB)
# ============================================================================

async def show_artist(chat_id: int, artist_id: int, page: int = 1,
                      message_to_edit: Optional[Message] = None, owner_id: int = None, force=False):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال پردازش هنرمند...*{FOOTER}", reply_markup=close_btn)

    try:
        artist_data = await get_or_crawl_artist(artist_id=artist_id, status_msg=status_msg, force=force)
        if not artist_data:
            await send_error_with_retry(bot, chat_id, f"هنرمند یافت نشد.",
                                        f"artist_retry:{artist_id}", status_msg)
            return
        artist_data = artist_data['results'][0]
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
        random_collection = collections[random.randint(0, len(collections) - 2)] if collections else None
        artwork_url = get_high_res_artwork(random_collection.get("artworkUrl100") if random_collection else None,
                                           size=600)
        markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])
        markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])
        text += FOOTER
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup),
                           cache_id=str(random_collection['collectionId']) if random_collection else None,
                           artwork_url=artwork_url, owner_id=owner_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش هنرمند: {str(e)[:100]}",
                                    f"artist_retry:{artist_id}", status_msg)


async def show_collection(chat_id: int, collection_id: int, page: int = 1,
                          message_to_edit: Optional[Message] = None, owner_id: int = None, force=False):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال پردازش آلبوم...*{FOOTER}", reply_markup=close_btn)

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
                duration = format_duration(track.get('trackTimeMillis', 0))
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

        if collection_data.get("artistId"):
            markup.append([InlineKeyboardButton(
                text="🎤 مشاهده هنرمند",
                callback_data=f"artist:{collection_data['artistId']}:1"
            )])
        markup.append(
            [InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:collection:{collection_id}")])
        markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

        text += FOOTER

        artwork_url = get_high_res_artwork(collection_data.get("artworkUrl100"))
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup),
                           artwork_url=artwork_url, cache_id=collection_id, owner_id=owner_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش آلبوم: {str(e)[:100]}",
                                    f"collection_retry:{collection_id}", status_msg)


async def show_track(chat_id: int, track_id: int, message_to_edit: Optional[Message] = None, owner_id: int = None):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال بارگذاری اطلاعات آهنگ...*{FOOTER}", reply_markup=close_btn)

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
        markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

        text += FOOTER
        artwork_url = get_high_res_artwork(track.get("artworkUrl", track.get("artworkUrl100")))
        await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), artwork_url=artwork_url,
                           cache_id=track.get('collectionId'), owner_id=owner_id)
        await status_msg.delete()

    except Exception as e:
        await send_error_with_retry(bot, chat_id, f"خطا در نمایش آهنگ: {str(e)[:100]}",
                                    f"track_retry:{track_id}", status_msg)


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    logger.info(f"🎵 {BOT_NAME} Music Bot Starting (High Concurrency Mode)...")
    logger.info(f"Rate limit: {rate_limiter.max_requests} req/min per user")
    logger.info(f"Global rate limit: {rate_limiter.max_global} req/min")
    logger.info(f"File cache directory: {CACHE_DIR.absolute()}")
    bot.run()
