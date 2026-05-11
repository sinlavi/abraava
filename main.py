import logging
import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from functools import wraps
from collections import defaultdict

import aiohttp
import aiosqlite
import os
from balethon.objects import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboard,
)
from ytmusicapi import YTMusic
from balethon import Client

# ---- project config (assumed unchanged) ----
from config import (
    BOT_NAME,
    FOOTER,
    OFFLINE_MODE,
    ITEMS_PER_PAGE,
    BOT_TOKEN,
    DB_CHANNEL_ID,
    logger,  # already a logger instance
)
from crawlers.itunes import search_itunes, lookup_itunes
from crawlers.youtube import download_audio
from database.config import init_db, DB_PATH
from database.utils import (
    is_cached,
    get_artist_db,
    set_cached,
    store_album,
    store_artist,
    set_audio_cache,
    delete_cached,
    get_album_db,
    get_cached,
    get_track_db,
    store_track,
    get_audio_cache,
    local_search,
)
from utils import tag_mp3

# ---------- Logging improvements ----------
# Use the logger from config, add file/stream handlers if needed (config already did).
logging.getLogger("balethon").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("ytmusicapi").setLevel(logging.WARNING)

# ---------- Global rate limiter & semaphore ----------
# For 1M users, an in‑memory rate limiter is a single‑point bottleneck.
# In production use Redis‑based rate limiting (e.g. aioredis). Here we provide a simple
# sliding window counter that works for a single process and is enough for testing.
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.users: Dict[int, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, user_id: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            # remove timestamps older than period
            self.users[user_id] = [t for t in self.users[user_id] if now - t < self.period]
            if len(self.users[user_id]) >= self.max_calls:
                return False
            self.users[user_id].append(now)
            return True

# instantiate limiters (tune values for your infra)
SEARCH_LIMITER = RateLimiter(max_calls=15, period=60)      # 15 searches per 60 seconds per user
DOWNLOAD_LIMITER = RateLimiter(max_calls=3, period=120)    # 3 downloads per 2 minutes per user
TRENDING_LIMITER = RateLimiter(max_calls=10, period=60)    # 10 trending per minute per user

# global concurrency for downloads (to protect youtube-dl and bandwidth)
DOWNLOAD_SEM = asyncio.Semaphore(3)   # max 3 simultaneous downloads
YT_SEM = asyncio.Semaphore(5)        # max 5 parallel YTMusic searches

# ---------- YTMusic session management ----------
# Instead of a global YT object, we create one per search using a factory.
# This is safer and avoids stale connections.
async def get_ytmusic():
    # ytmusicapi is not async, but its calls are I/O bound --> run in executor
    return YTMusic()

# ---------- Helper functions (unchanged mostly) ----------
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
    return hashlib.md5(f"{type_}:{term}".encode()).hexdigest()[:10]

async def edit_or_send(bot: Client, chat_id: int, message_to_edit: Optional[Message], text: str,
                       markup, artwork_url: str = None) -> Optional[Message]:
    """Safely edit or send a new message. Returns the new message or None."""
    try:
        if artwork_url:
            msg = await bot.send_photo(chat_id, photo=artwork_url, caption=text, reply_markup=markup)
        else:
            msg = await bot.send_message(chat_id, text, reply_markup=markup)

        if message_to_edit:
            try:
                await message_to_edit.delete()
            except Exception:
                pass
        return msg
    except Exception as e:
        logger.error(f"edit_or_send failed: {e}")
        return None

# ---------- Rate‑limit decorators ----------
def rate_limited(limiter: RateLimiter, error_msg: str = "⏳ لطفاً کمی صبر کنید و دوباره تلاش کنید."):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # callback queries always have a from_user in callback_query.message.chat.id?
            # We'll extract user_id from the handler arguments.
            # For message handlers: user_id = message.from_user.id
            # For callback handlers: callback_query.message.chat.id (but it's chat, not user; we need user: callback_query.from_user.id)
            user_id = None
            # try to find 'message' or 'callback_query' in args/kwargs
            if "message" in kwargs:
                user_id = kwargs["message"].from_user.id
            elif "callback_query" in kwargs:
                user_id = kwargs["callback_query"].from_user.id
            if user_id is None:
                # fallback: scan args for a balethon object
                for arg in args:
                    if hasattr(arg, "from_user") and hasattr(arg.from_user, "id"):
                        user_id = arg.from_user.id
                        break
            if user_id is None:
                # cannot rate limit, just run
                return await func(*args, **kwargs)

            if not await limiter.check(user_id):
                # send a warning message (if we have a chat_id we can reply)
                chat_id = None
                if "message" in kwargs:
                    chat_id = kwargs["message"].chat.id
                elif "callback_query" in kwargs:
                    chat_id = kwargs["callback_query"].message.chat.id
                if chat_id:
                    await bot.send_message(chat_id, error_msg)
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# ---------- Bot initialization ----------
bot = Client(token=BOT_TOKEN)

@bot.on_initialize()
async def on_initialize():
    await init_db()
    logger.info("Database initialized (relational). Note: for 1M users, switch to PostgreSQL + asyncpg.")

# ---------- Background tasks ----------
async def crawl_artist_albums(artist_id: int, status_msg: Message = None):
    if OFFLINE_MODE:
        return
    cache_id = f"artist_albums:{artist_id}"
    if await is_cached(cache_id):
        return
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آلبوم‌های هنرمند...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(artist_id, "album")
    if data and data.get("resultCount", 0) > 0:
        albums = []
        for item in data["results"]:
            if item.get("wrapperType") == "collection" and item.get("collectionType") == "Album":
                album_id = item["collectionId"]
                albums.append(album_id)
                await store_album(item)
        await set_cached(cache_id, "artist_albums", {"albums": albums})

async def get_artist(artist_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    db_data = await get_artist_db(artist_id)
    if db_data:
        return db_data
    if OFFLINE_MODE:
        logger.info(f"Offline: artist {artist_id} not found")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات هنرمند...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(artist_id)
    if data and data.get("results"):
        for item in data["results"]:
            if item.get("wrapperType") == "artist":
                await store_artist(item)
        asyncio.create_task(crawl_artist_albums(artist_id, status_msg))
        return data
    return None

async def crawl_album_tracks(album_id: int, status_msg: Message = None):
    if OFFLINE_MODE:
        return
    cache_id = f"album_tracks:{album_id}"
    if await is_cached(cache_id):
        return
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت آهنگ‌های آلبوم...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(album_id, "song")
    if data and data.get("resultCount", 0) > 0:
        tracks = []
        for item in data["results"]:
            if item.get("wrapperType") == "track" and item.get("kind") == "song":
                track_id = item["trackId"]
                tracks.append(track_id)
                await store_track(item)
        await set_cached(cache_id, "album_tracks", {"tracks": tracks})

async def get_album(album_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    db_data = await get_album_db(album_id)
    if db_data:
        return db_data
    if OFFLINE_MODE:
        logger.info(f"Offline: album {album_id} not found")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آلبوم...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(album_id)
    if data and data.get("results"):
        for item in data["results"]:
            if item.get("wrapperType") == "collection":
                await store_album(item)
        await crawl_album_tracks(album_id, status_msg)
        return data
    return None

async def get_track(track_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    db_data = await get_track_db(track_id)
    if db_data:
        return db_data
    if OFFLINE_MODE:
        logger.info(f"Offline: track {track_id} not found")
        return None
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آهنگ...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(track_id)
    if data and data.get("results"):
        for item in data["results"]:
            if item.get("wrapperType") == "track":
                await store_track(item)
        return data
    return None

# ---------- YouTube Music Search ----------
async def search_youtube_track(query: str) -> Optional[str]:
    if OFFLINE_MODE:
        return None
    async with YT_SEM:
        try:
            yt = await asyncio.get_event_loop().run_in_executor(None, YTMusic)
            results = await asyncio.get_event_loop().run_in_executor(
                None, yt.search, query, "songs", 1
            )
            if results and isinstance(results, list) and len(results) > 0:
                return results[0].get("videoId")
        except Exception as e:
            logger.error(f"YTMusic search error: {e}")
    return None

# ---------- Download & Caching Logic ----------
async def send_audio_with_retry(bot: Client, chat_id: int, audio_path: str, file_name: str, caption: str,
                                max_retries: int = 3, direct: bool = False):
    """Send audio with retry on gateway timeout or internal errors."""
    last_exception = None
    abs_audio_path = os.path.abspath(str(audio_path))
    if not os.path.exists(abs_audio_path):
        raise FileNotFoundError(f"File not found: {abs_audio_path}")

    target_chat = chat_id if direct else int(DB_CHANNEL_ID)
    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_audio_path, 'rb') as audio_file:
                return await bot.send_document(
                    chat_id=target_chat,
                    document=audio_file,
                    caption=caption
                )
        except Exception as e:
            error_str = str(e)
            if any(code in error_str for code in ("504", "500", "Time-out")):
                logger.warning(f"send_audio error, retry {attempt}/{max_retries}: {e}")
                last_exception = e
                await asyncio.sleep(attempt * 2)
            else:
                raise
    raise last_exception

async def send_cached_or_download(bot: Client, chat_id: int, track_id: int):
    # Rate limit check done via decorator on the handler, so safe here.
    status_msg = await bot.send_message(chat_id, f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*{FOOTER}")

    channel_msg_id = await get_audio_cache(track_id)
    if channel_msg_id and DB_CHANNEL_ID:
        try:
            await status_msg.edit("در حال ارسال فایل...")
            await bot.forward_message(chat_id, from_chat_id=int(DB_CHANNEL_ID), message_id=channel_msg_id)
            await status_msg.edit(f"✅ آهنگ با موفقیت از دیتابیس {BOT_NAME} دریافت شد.{FOOTER}")
            return
        except Exception as e:
            logger.error(f"Forward failed: {e}, will re-download")

    if OFFLINE_MODE:
        await status_msg.edit(f"❌ آهنگ در دیتابیس محلی یافت نشد و بات در حالت آفلاین است.{FOOTER}")
        return

    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await status_msg.edit(f"❌ خطا در دریافت اطلاعات آهنگ.{FOOTER}")
        return

    track = track_data["results"][0]
    t_name = track.get("trackName", "Unknown Title")
    ye = track.get("releaseDate", "").split("-")[0]
    a_name = track.get("artistName", "Unknown Artist")
    album_name = track.get("collectionName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100"), size=600)

    query = f"{t_name} {a_name} {album_name} {ye}"
    await status_msg.edit(f"🔍 جستجوی سورس باکیفیت آهنگ در یوتیوب موزیک...{FOOTER}")

    video_id = await search_youtube_track(query)
    if not video_id:
        await status_msg.edit(f"❌ نتوانستیم لینک یوتیوب موزیک را برای این آهنگ پیدا کنیم.{FOOTER}")
        return
    video_url = f"https://music.youtube.com/watch?v={video_id}"

    await status_msg.edit(f"⏳ در حال دانلود و آماده‌سازی آهنگ (روش‌های پیشرفته ضد تحریم)...{FOOTER}")

    mp3_path = None
    try:
        # Global download semaphore
        async with DOWNLOAD_SEM:
            mp3_path_str = await asyncio.get_event_loop().run_in_executor(
                None, download_audio, video_url
            )
        if not mp3_path_str:
            await status_msg.edit(f"❌ دانلود با شکست مواجه شد — همه ۸ روش ناموفق بودند.{FOOTER}")
            return

        mp3_path = Path(mp3_path_str)
        if not mp3_path.exists():
            await status_msg.edit(f"❌ خطای داخلی: فایل دانلود شده یافت نشد.{FOOTER}")
            return

        file_size_mb = mp3_path.stat().st_size / (1024 * 1024)

        # Download cover image
        cover_bytes = None
        if cover_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(cover_url) as resp:
                        if resp.status == 200:
                            cover_bytes = await resp.read()
            except Exception as e:
                logger.error(f"Cover download failed: {e}")

        # Tag MP3
        await asyncio.get_event_loop().run_in_executor(
            None, tag_mp3, mp3_path, t_name, a_name, album_name, cover_bytes
        )

        caption = f"🎵 {t_name}\n🎤 {a_name}\n📀 {album_name}\n🔊 MP3 320 kbps | {file_size_mb:.1f} MB{FOOTER}"

        if DB_CHANNEL_ID:
            try:
                await status_msg.edit(f"☁️ در حال آپلود در سرورهای ابری {BOT_NAME}...{FOOTER}")
                db_msg = await send_audio_with_retry(
                    bot, chat_id, str(mp3_path), f"{t_name}.mp3", caption
                )
                if db_msg and db_msg.message_id:
                    await bot.forward_message(chat_id, from_chat_id=int(DB_CHANNEL_ID), message_id=db_msg.message_id)
                    await set_audio_cache(track_id, int(db_msg.message_id))
                    await status_msg.edit(f"✅ دانلود و پردازش با موفقیت انجام شد.{FOOTER}")
                else:
                    raise Exception("No message ID from DB channel")
            except Exception as e:
                logger.error(f"Caching upload error: {e}")
                await send_audio_with_retry(bot, chat_id, str(mp3_path), f"{t_name}.mp3", caption, direct=True)
                await status_msg.edit(f"✅ آهنگ مستقیما ارسال شد (خطا در ذخیره دیتابیس).{FOOTER}")
        else:
            await send_audio_with_retry(bot, chat_id, str(mp3_path), f"{t_name}.mp3", caption)
            await status_msg.edit(f"✅ دانلود و ارسال با موفقیت انجام شد.{FOOTER}")

    except Exception as e:
        logger.exception("Download error")
        await status_msg.edit(f"❌ خطا در عملیات: {e}{FOOTER}")
    finally:
        if mp3_path and mp3_path.exists():
            try:
                mp3_path.unlink()
            except Exception as e:
                logger.error(f"Could not delete temp file {mp3_path}: {e}")

async def send_voice_preview(chat_id: int, track_id: int):
    status_msg = await bot.send_message(chat_id, f"⏳ در حال دریافت پیش‌نمایش...{FOOTER}")
    track_data = await get_track(track_id)
    if not track_data or not track_data.get("results"):
        await status_msg.edit(f"❌ اطلاعات آهنگ یافت نشد.{FOOTER}")
        return

    track = track_data["results"][0]
    preview_url = track.get("previewUrl")
    if not preview_url:
        await status_msg.edit(f"❌ متاسفانه پیش‌نمایشی برای این آهنگ موجود نیست.{FOOTER}")
        return

    try:
        await bot.send_voice(chat_id, voice=preview_url,
                             caption=f"🎧 پیش‌نمایش صوتی آهنگ {track.get('trackName')}{FOOTER}")
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Failed to send audio preview: {e}")
        await status_msg.edit(f"❌ خطا در ارسال پیش‌نمایش.{FOOTER}")

# ---------- Message handler (now supports free-text search) ----------
@bot.on_message()
async def handle_message(message: Message):
    if not message.content:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    is_group = message.chat.type in ["group", "supergroup", "channel"]

    # Strip mention if group
    msg_text = message.content.strip()
    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention in msg_text:
            msg_text = msg_text.replace(bot_mention, "").strip()
        else:
            # only respond to commands without mention if explicitly allowed (like /start@BotName)
            if msg_text.startswith("/"):
                # optional: still process commands if they include bot username? skip for simplicity
                return
            return  # ignore normal group messages without mention

    # Now msg_text is either a command or a search query (private or mention‑stripped)
    if not msg_text:
        return

    # ---- Command routing ----
    if msg_text.startswith("/start"):
        await message.reply(
            f"🎵 *به ربات جستجو و دانلود موسیقی {BOT_NAME} خوش آمدید!*\n\n"
            "*دستورات:*\n"
            "/search artist:<نام> - جستجوی هنرمند\n"
            "/search album:<نام> - جستجوی آلبوم\n"
            "/search track:<نام> - جستجوی آهنگ\n"
            "/search <نام> - جستجوی ترکیبی\n"
            "/trending - آهنگ‌های پرطرفدار iTunes\n"
            "/help - راهنما\n"
            "/about - درباره ربات\n\n"
            "*نکته:* در گروه‌ها ربات را منشن کنید و سپس درخواست خود را بنویسید (مثال: @MyMusicBot ed sheeran).\n"
            f"{FOOTER}"
        )
        return

    elif msg_text.startswith("/help"):
        await message.reply(
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            "برای جستجوی موزیک کافیست عبارت جستجو را وارد کنید.\n"
            "مثال: ed sheeran\n\n"
            "همچنین می‌توانید از دستور /trending برای دیدن آهنگ‌های برتر iTunes استفاده کنید.\n\n"
            "⚠️ در گروه‌ها باید آیدی ربات را تگ کنید و سپس عبارت جستجو را بنویسید:\n"
            f"@{bot.user.username} hello"
            f"{FOOTER}"
        )
        return

    elif msg_text.startswith("/about"):
        await message.reply(
            f"ℹ️ *درباره ربات {BOT_NAME}*\n\n"
            f"این ربات یک دستیار هوشمند برای جستجو در دیتابیس عظیم iTunes و دانلود باکیفیت‌ترین سورس موجود از YouTube Music است.\n"
            f"تمامی آهنگ‌ها پیش از ارسال پردازش و تگ‌گذاری می‌شوند."
            f"{FOOTER}"
        )
        return

    # ---- free‑text search (no /search prefix needed) ----
    # If the message is not a recognized command, treat it as a search query
    query = msg_text
    if query.startswith("/search"):
        # allow optional /search prefix
        parts = query.split(" ", 1)
        if len(parts) < 2:
            await message.reply("❌ لطفاً عبارت جستجو را وارد کنید.")
            return
        query = parts[1].strip()

    if not query:
        return

    # rate limiting for search
    if not await SEARCH_LIMITER.check(user_id):
        await message.reply("⏳ لطفاً کمی صبر کنید و سپس دوباره جستجو کنید.")
        return

    # Determine entity type (artist: / album: / track:)
    if ":" in query:
        type_, term = query.split(":", 1)
        type_ = type_.lower()
        if type_ not in ["artist", "album", "track"]:
            await message.reply("❌ نوع جستجو نامعتبر است. (artist, album, track)")
            return
    else:
        type_ = "all"
        term = query

    entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
    status_msg = await message.reply(f"🔍 *در حال جستجوی {type_} : {term}...*{FOOTER}")

    # Search with caching
    search_id = generate_search_hash(type_, term)
    cache_key = f"search:{search_id}"

    results = None
    if not OFFLINE_MODE:
        if type_ == "all":
            results = await search_itunes(term, entity=None, limit=50)
        else:
            results = await search_itunes(term, entity_map[type_], limit=50)

    if results is None:
        results = await local_search(term, type_)

    if results and results.get("resultCount", 0) > 0:
        await set_cached(cache_key, "search", {"type": type_, "term": term, "data": results})
        if not OFFLINE_MODE:
            for item in results["results"]:
                if item.get("wrapperType") == "artist":
                    await store_artist(item)
                elif item.get("wrapperType") == "collection":
                    await store_album(item)
                elif item.get("wrapperType") == "track":
                    await store_track(item)
    else:
        await status_msg.edit(f"❌ *هیچ نتیجه‌ای برای '{term}' یافت نشد.*{FOOTER}")
        return

    await status_msg.delete()
    await send_search_page(chat_id, search_id, 1, original_term=term)

async def send_search_page(chat_id: int, search_id: str, page: int,
                           message_to_edit: Optional[Message] = None,
                           original_term: Optional[str] = None):
    cache_key = f"search:{search_id}"
    cache_data = await get_cached(cache_key)
    if not cache_data:
        text = f"❌ خطا در بارگذاری نتایج.{FOOTER}"
        if message_to_edit:
            try: await message_to_edit.edit(text)
            except: pass
        else:
            await bot.send_message(chat_id, text)
        return

    type_ = cache_data["type"]
    term = cache_data["term"]
    results_list = cache_data["data"]["results"]
    total_items = len(results_list)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = results_list[start_idx:end_idx]

    markup = []
    header = ""
    if type_ == "all":
        header = f"📋 *نتایج جستجوی ترکیبی برای: {term}*\nتعداد کل: {total_items} مورد"
    else:
        type_fa = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}
        header = f"📋 *نتایج جستجو برای {type_fa[type_]} : {term}*\nتعداد کل: {total_items} مورد"

    for i, item in enumerate(page_items, 1):
        wrapper = item.get("wrapperType")
        if type_ == "all":
            if wrapper == "artist":
                btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
                callback = f"artist:{item['artistId']}:1"
            elif wrapper == "collection":
                btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
                callback = f"album:{item['collectionId']}:1"
            elif wrapper == "track":
                btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
                callback = f"track:{item['trackId']}"
            else:
                continue
        else:
            if type_ == "artist":
                btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
                callback = f"artist:{item['artistId']}:1"
            elif type_ == "album":
                btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
                callback = f"album:{item['collectionId']}:1"
            elif type_ == "track":
                btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:45]} - {item.get('artistName', 'نامشخص')}"
                callback = f"track:{item['trackId']}"
        markup.append([InlineKeyboardButton(text=btn_text, callback_data=callback)])

    if total_pages > 1:
        pagination = create_pagination_row(f"page:search:{search_id}", page, total_pages)
        markup.append(pagination)

    # refinement row
    refine_term = term
    markup.append([
        InlineKeyboardButton("🔍 آلبوم‌ها", f"refine:album:{refine_term}"),
        InlineKeyboardButton("🔍 هنرمندان", f"refine:artist:{refine_term}"),
        InlineKeyboardButton("🔍 آهنگ‌ها", f"refine:track:{refine_term}")
    ])
    markup.append([InlineKeyboardButton("❌ بستن", callback_data="close")])

    text = header + FOOTER
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup))

# ---------- Callback query handler ----------
@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    logger.debug(f"Callback: {data} from user {user_id}")

    if data == "ignore":
        return
    if data == "close":
        try:
            await callback_query.message.delete()
        except:
            pass
        return

    try:
        parts = data.split(":")
        # pagination for search results
        if data.startswith("page:search:"):
            search_id = parts[2]
            page = int(parts[3])
            await send_search_page(chat_id, search_id, page, callback_query.message)

        # refinement (filter by type)
        elif data.startswith("refine:"):
            entity = parts[1]
            term = parts[2]
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            if entity not in entity_map:
                return
            # rate limit search again? reuse SEARCH_LIMITER
            if not await SEARCH_LIMITER.check(user_id):
                await bot.send_message(chat_id, "⏳ لطفاً صبر کنید.")
                return
            status = await bot.send_message(chat_id, f"🔍 *در حال جستجوی {entity} برای: {term}...*{FOOTER}")
            results = None
            if not OFFLINE_MODE:
                results = await search_itunes(term, entity=entity_map[entity], limit=50)
            if results is None:
                results = await local_search(term, entity)
            if results and results.get("resultCount", 0) > 0:
                search_id = generate_search_hash(entity, term)
                await set_cached(f"search:{search_id}", "search",
                                 {"type": entity, "term": term, "data": results})
                if not OFFLINE_MODE:
                    for item in results["results"]:
                        if item.get("wrapperType") == "artist":
                            await store_artist(item)
                        elif item.get("wrapperType") == "collection":
                            await store_album(item)
                        elif item.get("wrapperType") == "track":
                            await store_track(item)
                await status.delete()
                await send_search_page(chat_id, search_id, 1, original_term=term)
            else:
                await status.edit(f"❌ *نتیجه‌ای برای '{term}' در بخش {entity} یافت نشد.*{FOOTER}")

        # show artist
        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist(chat_id, artist_id, page, callback_query.message)

        # show album
        elif data.startswith("album:"):
            album_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            # if only one track, jump to track view directly? Optional.
            cached_album_tracks = await get_cached(f"album_tracks:{album_id}")
            if not cached_album_tracks:
                await crawl_album_tracks(album_id)
                cached_album_tracks = await get_cached(f"album_tracks:{album_id}")
            if cached_album_tracks and "tracks" in cached_album_tracks:
                track_ids = cached_album_tracks["tracks"]
                if len(track_ids) == 1:
                    await show_track(chat_id, track_ids[0], callback_query.message)
                    return
            await show_album(chat_id, album_id, page, callback_query.message)

        # show track
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track(chat_id, track_id, callback_query.message)

        # download
        elif data.startswith("download:"):
            track_id = int(parts[1])
            # rate limit downloads
            if not await DOWNLOAD_LIMITER.check(user_id):
                await callback_query.answer("⏳ برای دانلود مجدد لطفاً کمی صبر کنید.", show_alert=True)
                return
            await send_cached_or_download(bot, chat_id, track_id)

        # voice preview
        elif data.startswith("preview:"):
            track_id = int(parts[1])
            await send_voice_preview(chat_id, track_id)

        # recrawl (refresh)
        elif data.startswith("recrawl:"):
            type_ = parts[1]
            id_ = int(parts[2])
            # delete cache and DB entries
            if type_ == "artist":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM artist WHERE artistId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"artist:{id_}")
                await delete_cached(f"artist_albums:{id_}")
                await show_artist(chat_id, id_, 1, callback_query.message)
            elif type_ == "album":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM album WHERE collectionId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"album:{id_}")
                await delete_cached(f"album_tracks:{id_}")
                await show_album(chat_id, id_, 1, callback_query.message)
            elif type_ == "track":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM track WHERE trackId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"track:{id_}")
                await show_track(chat_id, id_, callback_query.message)

    except Exception as e:
        logger.error(f"Callback error {data}: {e}")

# ---------- Show functions ----------
async def show_artist(chat_id: int, artist_id: int, page: int = 1, message_to_edit: Optional[Message] = None):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال پردازش هنرمند...*{FOOTER}")
    data = await get_artist(artist_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit(f"❌ *هنرمند یافت نشد.*{FOOTER}")
        return
    artist = data["results"][0]
    text = f"*🎤 هنرمند:* {artist.get('artistName', 'نامشخص')}\n"
    text += f"*🎭 سبک:* {artist.get('primaryGenreName', 'نامشخص')}\n"
    if artist.get("artistLinkUrl"):
        text += f"*🔗 لینک آیتونز:* [مشاهده]({artist['artistLinkUrl']})\n"

    albums_cache = await get_cached(f"artist_albums:{artist_id}")
    if not albums_cache or "albums" not in albums_cache:
        await crawl_artist_albums(artist_id, status_msg)
        albums_cache = await get_cached(f"artist_albums:{artist_id}")

    albums = []
    if albums_cache and "albums" in albums_cache:
        for album_id in albums_cache["albums"]:
            album_data = await get_album_db(album_id)
            if album_data and album_data.get("results"):
                albums.append(album_data["results"][0])
            else:
                album_data_cache = await get_cached(f"album:{album_id}")
                if album_data_cache and album_data_cache.get("results"):
                    albums.append(album_data_cache["results"][0])

    markup = []
    if albums:
        total_items = len(albums)
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = albums[start_idx:end_idx]
        text += f"\n*📀 آلبوم‌ها ({total_items}):*\n"
        for i, album in enumerate(page_items, start_idx + 1):
            text += f"{i}. {album.get('collectionName', 'نامشخص')[:40]}\n"
        for album in page_items:
            markup.append([InlineKeyboardButton(
                f"📀 {album.get('collectionName', '')[:40]}",
                callback_data=f"album:{album['collectionId']}:1"
            )])
        if total_pages > 1:
            pagination_row = create_pagination_row(f"artist:{artist_id}", page, total_pages)
            markup.append(pagination_row)

    markup.append([InlineKeyboardButton("🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])
    markup.append([InlineKeyboardButton("❌ بستن", callback_data="close")])

    text += FOOTER
    await status_msg.delete()
    artwork_url = get_high_res_artwork(artist.get("artworkUrl100"))
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), artwork_url=artwork_url)

async def show_album(chat_id: int, album_id: int, page: int = 1, message_to_edit: Optional[Message] = None):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال پردازش آلبوم...*{FOOTER}")
    data = await get_album(album_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit(f"❌ *آلبوم یافت نشد.*{FOOTER}")
        return
    album = data["results"][0]
    release_date = album.get('releaseDate', 'نامشخص')[:10] if album.get('releaseDate') else 'نامشخص'
    text = f"*📀 آلبوم:* {album.get('collectionName', 'نامشخص')}\n"
    text += f"*🎤 هنرمند:* {album.get('artistName', 'نامشخص')}\n"
    text += f"*📅 انتشار:* {release_date}\n"
    text += f"*🎭 سبک:* {album.get('primaryGenreName', 'نامشخص')}\n"
    if album.get("collectionViewUrl"):
        text += f"*🔗 لینک آیتونز:* [مشاهده]({album['collectionViewUrl']})\n"

    tracks_cache = await get_cached(f"album_tracks:{album_id}")
    if not tracks_cache or "tracks" not in tracks_cache:
        await crawl_album_tracks(album_id, status_msg)
        tracks_cache = await get_cached(f"album_tracks:{album_id}")

    tracks = []
    if tracks_cache and "tracks" in tracks_cache:
        for track_id in tracks_cache["tracks"]:
            track_data = await get_track_db(track_id)
            if track_data and track_data.get("results"):
                tracks.append(track_data["results"][0])
            else:
                track_data_cache = await get_cached(f"track:{track_id}")
                if track_data_cache and track_data_cache.get("results"):
                    tracks.append(track_data_cache["results"][0])

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
            markup.append([InlineKeyboardButton(
                f"🎵 {track.get('trackName', '')[:35]} - {track.get('artistName', '')[:30]}",
                callback_data=f"track:{track['trackId']}"
            )])
        if total_pages > 1:
            pagination_row = create_pagination_row(f"album:{album_id}", page, total_pages)
            markup.append(pagination_row)

    if album.get("artistId"):
        markup.append([InlineKeyboardButton("🎤 مشاهده هنرمند", callback_data=f"artist:{album['artistId']}:1")])
    markup.append([InlineKeyboardButton("🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:album:{album_id}")])
    markup.append([InlineKeyboardButton("❌ بستن", callback_data="close")])

    text += FOOTER
    await status_msg.delete()
    artwork_url = get_high_res_artwork(album.get("artworkUrl100"))
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), artwork_url=artwork_url)

async def show_track(chat_id: int, track_id: int, message_to_edit: Optional[Message] = None):
    status_msg = await bot.send_message(chat_id, f"🔄 *در حال بارگذاری اطلاعات آهنگ...*{FOOTER}")
    data = await get_track(track_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit(f"❌ *آهنگ یافت نشد.*{FOOTER}")
        return
    track = data["results"][0]
    duration = format_duration(track.get('trackTimeMillis', 0))
    release_date = track.get('releaseDate', 'نامشخص')[:10] if track.get('releaseDate') else 'نامشخص'
    text = f"*🎵 آهنگ:* {track.get('trackName', 'نامشخص')}\n"
    text += f"*🎤 هنرمند:* {track.get('artistName', 'نامشخص')}\n"
    text += f"*📀 آلبوم:* {track.get('collectionName', 'نامشخص')}\n"
    text += f"*⏱️ مدت:* {duration}\n"
    text += f"*🎭 سبک:* {track.get('primaryGenreName', 'نامشخص')}\n"
    text += f"*📅 انتشار:* {release_date}\n"
    if track.get("trackViewUrl"):
        text += f"*🔗 لینک آیتونز:* [مشاهده]({track['trackViewUrl']})\n"

    markup = []
    download_row = [InlineKeyboardButton("⬇️ دانلود", callback_data=f"download:{track_id}")]
    if track.get("previewUrl"):
        download_row.append(InlineKeyboardButton("🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"))
    markup.append(download_row)

    nav_row = []
    if track.get('collectionId'):
        nav_row.append(InlineKeyboardButton("📀 آلبوم", callback_data=f"album:{track['collectionId']}:1"))
    if track.get('artistId'):
        nav_row.append(InlineKeyboardButton("🎤 هنرمند", callback_data=f"artist:{track['artistId']}:1"))
    if nav_row:
        markup.append(nav_row)

    markup.append([InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}")])
    markup.append([InlineKeyboardButton("❌ بستن", callback_data="close")])

    text += FOOTER
    await status_msg.delete()
    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), artwork_url=artwork_url)

# ---------- Entry point ----------
if __name__ == "__main__":
    logger.info(f"🎵 {BOT_NAME} Music Bot starting (v2 – scalable, rate‑limited, free‑text search)...")
    # For 1M users, ensure the database backend is PostgreSQL (not aiosqlite) and use connection pooling.
    # The in‑memory rate limiter should be replaced with Redis for multi‑process deployment.
    bot.run()
