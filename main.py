import logging
import asyncio
import hashlib
import aiohttp
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import os
import time
from collections import defaultdict
from balethon.objects import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboard
from ytmusicapi import YTMusic
from balethon import Client
from config import BOT_NAME, FOOTER, OFFLINE_MODE, ITEMS_PER_PAGE, BOT_TOKEN, DB_CHANNEL_ID, INFO_CHANNEL_ID, logger
from crawlers.itunes import search_itunes, lookup_itunes
from crawlers.youtube import download_audio
from database.config import init_db, DB_PATH
from database.utils import is_cached, get_artist_db, set_cached, store_album, store_artist, set_audio_cache, \
    delete_cached, get_album_db, get_cached, get_track_db, store_track, get_audio_cache, local_search, store_user, \
    get_users_db
from utils import tag_mp3

YT = None  # YTMusic instance initialized later


# ---------- Rate Limiting ----------
class RateLimiter:
    def __init__(self, max_requests: int = 30, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.users = defaultdict(list)
        self.global_requests = []
        self.max_global = 1000  # Max global requests per minute

    async def check_user(self, user_id: int) -> tuple[bool, int]:
        """Check if user has exceeded rate limit. Returns (allowed, wait_time)"""
        now = time.time()
        user_requests = self.users[user_id]

        # Clean old requests
        user_requests = [t for t in user_requests if now - t < self.time_window]
        self.users[user_id] = user_requests

        # Global rate limit
        self.global_requests = [t for t in self.global_requests if now - t < self.time_window]

        if len(self.global_requests) >= self.max_global:
            wait_time = int(self.time_window - (now - self.global_requests[0]))
            return False, wait_time

        if len(user_requests) >= self.max_requests:
            wait_time = int(self.time_window - (now - user_requests[0]))
            return False, wait_time

        user_requests.append(now)
        self.global_requests.append(now)
        return True, 0

    def get_user_remaining(self, user_id: int) -> int:
        now = time.time()
        user_requests = [t for t in self.users[user_id] if now - t < self.time_window]
        return max(0, self.max_requests - len(user_requests))


rate_limiter = RateLimiter(max_requests=30, time_window=60)

# ---------- User Management ----------
user_states = {}  # Track user states for conversation
user_last_message = {}  # Track last message time for spam prevention
broadcast_queue = asyncio.Queue()  # Queue for broadcast messages

# ---------- Advanced Logging ----------
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


# ---------- Crawlers (modified to use relational DB) ----------
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
        logger.info(f"Offline mode: artist {artist_id} not in local DB")
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
        logger.info(f"Offline mode: album {album_id} not in local DB")
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
        logger.info(f"Offline mode: track {track_id} not in local DB")
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


# ---------- YouTube Music Helper ----------
async def search_youtube_track(query: str) -> Optional[str]:
    if OFFLINE_MODE:
        logger.info("Offline mode: skipping YouTube search")
        return None
    global YT
    if YT is None:
        YT = YTMusic()
    try:
        results = YT.search(query, filter="songs", limit=1)
        if results and isinstance(results, list) and len(results) > 0:
            return results[0].get("videoId")
    except Exception as e:
        logger.error(f"YTMusic search error: {e}")
    return None


# ---------- Download & Caching Logic ----------
async def send_audio_with_retry(bot: Client, chat_id: int, audio_path: str, file_name: str, caption: str,
                                max_retries=3, direct=False):
    """Send audio with retry on gateway timeout or internal errors."""
    last_exception = None
    abs_audio_path = os.path.abspath(str(audio_path))

    if not os.path.exists(abs_audio_path):
        logger.error(f"File not found for upload: {abs_audio_path}")
        raise FileNotFoundError(f"File not found: {abs_audio_path}")
    chat_to_send = DB_CHANNEL_ID
    if direct:
        chat_to_send = chat_id
    logger.info(f"Sending audio: {abs_audio_path} to chat {chat_to_send}")

    for attempt in range(1, max_retries + 1):
        try:
            with open(abs_audio_path, 'rb') as audio_file:
                logger.info('Sending audio...')
                return await bot.send_document(
                    chat_id=int(chat_to_send),
                    document=audio_file,
                    caption=caption
                )
        except Exception as e:
            error_str = str(e)
            if "504" in error_str or "500" in error_str or "Time-out" in error_str:
                logger.warning(f"send_audio network/server error, retry {attempt}/{max_retries}: {e}")
                last_exception = e
                await asyncio.sleep(attempt * 2)
            else:
                logger.error(f"Upload failed fatally: {e}")
                raise e
    raise last_exception


async def send_cached_or_download(bot: Client, chat_id: int, track_id: int):
    status_msg = await bot.send_message(chat_id, f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*{FOOTER}")

    channel_msg_id = await get_audio_cache(track_id)
    if channel_msg_id and DB_CHANNEL_ID:
        try:
            await status_msg.edit(f"در حال ارسال فایل...")
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
                logger.error(f"Failed to download cover: {e}")

        # Update metadata using mutagen
        await asyncio.get_event_loop().run_in_executor(
            None, tag_mp3, mp3_path, t_name, a_name, album_name, cover_bytes
        )

        caption = f"🎵 {t_name}\n🎤 {a_name}\n📀 {album_name}\n🔊 MP3 320 kbps | {file_size_mb:.1f} MB{FOOTER}"

        # Upload the tagged file to DB_CHANNEL first (if exists)
        if DB_CHANNEL_ID:
            try:
                await status_msg.edit(f"☁️ در حال آپلود در سرورهای ابری {BOT_NAME}...{FOOTER}")
                db_msg = await send_audio_with_retry(
                    bot, chat_id, str(mp3_path), f"{t_name}.mp3", caption
                )

                if db_msg and db_msg.id:
                    logger.info(db_msg)
                    await bot.forward_message(chat_id, from_chat_id=int(DB_CHANNEL_ID), message_id=db_msg.id)
                    await set_audio_cache(track_id, int(db_msg.id))
                    await status_msg.edit(f"✅ دانلود و پردازش با موفقیت انجام شد.{FOOTER}")
                else:
                    raise Exception("No message ID returned from DB Channel")
            except Exception as e:
                logger.error(f"Error caching to DB_CHANNEL: {e}")
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
                logger.error(f"Failed to delete temp file {mp3_path}: {e}")


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


# ---------- Channel Membership Check ----------
async def check_channel_membership(bot: Client, user_id: int) -> bool:
    is_registered = await get_users_db(user_id)
    logger.info(is_registered)
    if is_registered == 0:
        await store_user(user_id)
    """Check if user is member of INFO_CHANNEL_ID"""
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
    """Check membership and send join request if not member"""
    is_member = await check_channel_membership(bot, user_id)
    if not is_member:
        markup = InlineKeyboard(*[
            [InlineKeyboardButton(text="🔗 عضویت در کانال", url=f"https://ble.ir/abraava")],
            [InlineKeyboardButton(text="✅ تایید عضویت", callback_data="verify_membership")]
        ])
        await bot.send_message(
            chat_id,
            f"⚠️ *برای استفاده از {BOT_NAME}، ابتدا باید در کانال ما عضو شوید.*\n\n"
            f"پس از عضویت، روی دکمه «تایید عضویت» کلیک کنید.{FOOTER}",
            reply_markup=markup
        )
        return False
    return True


# ---------- Helper functions ----------
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
                       markup, artwork_url: str = None):
    """Safely edit or send a message (caption or text) with optional photo."""
    if artwork_url:
        await bot.send_photo(chat_id, photo=artwork_url, caption=text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)

    if message_to_edit:
        try:
            await message_to_edit.delete()
        except:
            pass


# ---------- Bale Bot Initialization & Handlers ----------
bot = Client(token=BOT_TOKEN)


@bot.on_initialize()
async def on_initialize():
    await init_db()
    logger.info("Database initialized successfully (relational tables ready).")
    logger.info(f"Bot started with rate limiting: {rate_limiter.max_requests} req/min per user")

    # Start broadcast worker
    asyncio.create_task(broadcast_worker())


async def broadcast_worker():
    """Worker to send broadcast messages to all users"""
    logger.info("Broadcast worker started")
    while True:
        try:
            message_data = await broadcast_queue.get()
            users = message_data["users"]
            message = message_data["message"]
            success_count = 0
            fail_count = 0

            for user_id in users:
                try:
                    await bot.forward_message(
                        chat_id=user_id,
                        from_chat_id=int(INFO_CHANNEL_ID),
                        message_id=message.id
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)  # Rate limit for broadcasting
                except Exception as e:
                    logger.error(f"Failed to forward to user {user_id}: {e}")
                    fail_count += 1
                    await asyncio.sleep(0.1)

            logger.info(f"Broadcast completed: {success_count} success, {fail_count} failed")
            broadcast_queue.task_done()
        except Exception as e:
            logger.error(f"Broadcast worker error: {e}")
            await asyncio.sleep(1)


async def get_all_users() -> List[int]:
    """Get all unique user IDs from database"""
    users = set()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT DISTINCT user_id FROM user_sessions") as cursor:
                async for row in cursor:
                    users.add(row[0])
    except:
        pass
    return list(users)


async def parse_search_query(text: str) -> Optional[tuple[str, str]]:
    """Parse search query from text. Returns (type, term) or None"""
    text = text.strip()
    if not text:
        return None

    # Check for direct commands without /search
    if text.startswith("/search"):
        text = text[7:].strip()

    if ":" in text:
        parts = text.split(":", 1)
        type_ = parts[0].lower()
        term = parts[1].strip()
        if type_ in ["artist", "album", "track", "آهنگ", "آلبوم", "خواننده", "هنرمند"]:
            # Translate Persian to English
            persian_map = {
                "آهنگ": "track",
                "آلبوم": "album",
                "خواننده": "artist",
                "هنرمند": "artist"
            }
            type_ = persian_map.get(type_, type_)
            return (type_, term)
        else:
            return ("track", text)
    else:
        return ("track", text)


@bot.on_message()
async def handle_message(message):
    if message.content:
        if message.chat.id == int(INFO_CHANNEL_ID) and message.chat.type == "channel":
            await handle_channel_post(message)
            return

    is_group = message.chat.type in ["group", "supergroup", "channel"]
    msg_text = message.content
    user_id = message.author.id
    chat_id = message.chat.id

    # Rate limiting check
    date = await rate_limiter.check_user(user_id)
    allowed, wait_time = await rate_limiter.check_user(user_id)
    if not allowed:
        if is_group:
            return  # Silent ignore in groups
        await message.reply(
            f"⚠️ *محدودیت نرخ درخواست*\n\n"
            f"شما حداکثر {rate_limiter.max_requests} درخواست در دقیقه مجاز هستید.\n"
            f"لطفاً {wait_time} ثانیه صبر کنید.{FOOTER}"
        )
        return

    # Handle group mentions
    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention not in msg_text:
            return
        msg_text = msg_text.replace(bot_mention, "").strip()

    if not is_group and INFO_CHANNEL_ID and not msg_text.startswith('/start'):
        is_member = await check_channel_membership(bot, user_id)
        if not is_member:
            await require_membership(bot, chat_id, user_id)
            return
    # Command Handlers
    if msg_text.startswith("/start"):
        welcome_text = (
            f"🎵 *به ربات جستجو و دانلود موسیقی {BOT_NAME} خوش آمدید!*\n\n"
            f"✨ *قابلیت جدید:* کافیست نام آهنگ را مستقیماً بنویسید (بدون /search)!\n\n"
            "*دستورات:*\n"
            "/search artist:<نام> - جستجوی هنرمند\n"
            "/search album:<نام> - جستجوی آلبوم\n"
            "/search track:<نام> - جستجوی آهنگ\n"
            "/search <نام> - جستجوی ترکیبی\n"
            "`<نام>` - جستجوی مستقیم آهنگ\n\n"
            "*ویژگی‌ها:*\n"
            "• کش شدن و دیتابیس اختصاصی (ارسال فوری)\n"
            "• ثبت خودکار متادیتا (کاور، نام و خواننده) روی آهنگ\n"
            "• پخش پیش‌نمایش صوتی با لمس دکمه\n"
            "• دانلود سورس اورجینال از یوتیوب موزیک (ضد تحریم)\n"
            "• محدودیت نرخ: ۳۰ درخواست در دقیقه\n"
            "  🔊 MP3 320 kbps | ۸ روش عبور از تشخیص ربات"
        )

        if INFO_CHANNEL_ID:
            welcome_text += f"\n\n📢 *برای اطلاع از آخرین اخبار در کانال ما عضو شوید:* \n\nble.ir/join/4T95Zt7P5X"

        welcome_text += FOOTER

        markup = None
        if INFO_CHANNEL_ID:
            markup = InlineKeyboard([
                [InlineKeyboardButton(text="📢 کانال اطلاع‌رسانی", url=f"https://ble.ir/{INFO_CHANNEL_ID}")]
            ])

        await message.reply(welcome_text, reply_markup=markup)

    elif msg_text.startswith("/help"):
        await message.reply(
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            "برای جستجوی موزیک کافیست نام آن را بنویسید یا از دستور /search استفاده کنید.\n"
            "مثال: `Ed Sheeran Perfect`\n\n"
            "⚠️ اگر می‌خواهید ربات را در گروه‌ها استفاده کنید، حتما باید آیدی ربات را تگ کنید:\n"
            f"@{bot.user.username} Ed Sheeran\n\n"
            f"🔒 محدودیت: {rate_limiter.max_requests} درخواست در دقیقه"
            f"{FOOTER}"
        )
    elif msg_text.startswith("/about"):
        await message.reply(
            f"ℹ️ *درباره ربات {BOT_NAME}*\n\n"
            f"این ربات یک دستیار هوشمند برای جستجو در دیتابیس عظیم iTunes و دانلود باکیفیت‌ترین سورس موجود از YouTube Music به صورت ضدتحریم می‌باشد.\n"
            f"تمامی آهنگ‌ها پیش از ارسال توسط سرورهای ما پردازش و تگ‌گذاری (کاور و اطلاعات) می‌شوند.\n\n"
            f"⚡ *مقیاس‌پذیری:* آماده سرویس‌دهی به ۱ میلیون کاربر\n"
            f"🔒 *Rate Limit:* {rate_limiter.max_requests} req/min per user"
            f"{FOOTER}"
        )
    elif msg_text.startswith("/setting"):
        await message.reply(
            f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
            "در حال حاضر تنظیمات خاصی برای پیکربندی وجود ندارد و ربات در بهترین حالت کیفی (MP3 320kbps) تنظیم شده است."
            f"{FOOTER}"
        )
    elif msg_text.startswith("/stats"):
        # Admin stats
        remaining = rate_limiter.get_user_remaining(user_id)
        await message.reply(
            f"📊 *آمار شما*\n\n"
            f"• درخواست‌های باقی‌مانده: {remaining}/{rate_limiter.max_requests}\n"
            f"• پنجره زمانی: {rate_limiter.time_window} ثانیه\n"
            f"• وضعیت: {'✅ فعال' if remaining > 0 else '⛔ محدود شده'}"
            f"{FOOTER}"
        )
    else:
        # Direct search without /search command
        result = await parse_search_query(msg_text)
        if result:
            type_, term = result
            await handle_search_command(chat_id, user_id, type_, term, message)


async def handle_channel_post(message):
    """Handle new posts in INFO_CHANNEL_ID for broadcasting"""
    content = message.content
    should_broadcast = "#تبلیغ" in content or "#اطلاع_رسانی" in content

    if should_broadcast:
        logger.info(f"Broadcasting message from channel: {content[:100]}...")
        users = await get_all_users()
        if users:
            await broadcast_queue.put({"users": users, "message": message})
            logger.info(f"Broadcast queued for {len(users)} users")


async def handle_search_command(chat_id: int, user_id: int, type_: str, term: str, original_message: Message = None):
    """Handle search command with rate limiting"""
    entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
    type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "all": "همه"}

    status_msg = await bot.send_message(chat_id,
                                        f"🔍 *در حال جستجوی {type_fa_map.get(type_, type_)}: {term}...*{FOOTER}")

    search_id = generate_search_hash(type_, term)
    cache_key = f"search:{search_id}"

    results = None
    if not OFFLINE_MODE:
        if type_ == "all":
            results = await search_itunes(term, entity=None, limit=50)
        else:
            results = await search_itunes(term, entity_map.get(type_, type_), limit=50)

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
    await send_search_page(chat_id, search_id, 1, message_to_edit=None, original_term=term)


async def send_search_page(chat_id: int, search_id: str, page: int, message_to_edit: Optional[Message] = None,
                           original_term: Optional[str] = None):
    cache_key = f"search:{search_id}"
    cache_data = await get_cached(cache_key)
    if not cache_data:
        text = f"❌ خطایی در بارگذاری نتایج رخ داد (احتمالا سشن منقضی شده است).{FOOTER}"
        if message_to_edit:
            await message_to_edit.edit(text)
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
    if type_ == "all":
        header = f"📋 *نتایج جستجوی ترکیبی برای: {term}*\nتعداد کل: {total_items} مورد"
    else:
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}
        header = f"📋 *نتایج جستجو برای {type_fa_map[type_]}: {term}*\nتعداد کل: {total_items} مورد"

    for i, item in enumerate(page_items, 1):
        btn_text = "نامشخص"
        if type_ == "all":
            wrapper = item.get("wrapperType")
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
        pagination_row = create_pagination_row(f"page:search:{search_id}", page, total_pages)
        markup.append(pagination_row)

    refine_term = term
    markup.append([InlineKeyboardButton("🔍 آلبوم‌ها", f"refine:album:{refine_term}"),
                   InlineKeyboardButton("🔍 هنرمندان", f"refine:artist:{refine_term}"),
                   InlineKeyboardButton("🔍 آهنگ‌ها", f"refine:track:{refine_term}")])

    markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

    text = header + FOOTER
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup))


@bot.on_callback_query()
async def on_callback(callback_query: CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.author.id

    logger.info(f"Callback received: {data} from user {chat_id}")

    # Rate limiting for callbacks too
    allowed, wait_time = await rate_limiter.check_user(user_id)
    if not allowed:
        await bot.answer_callback_query(callback_query.id, f"⏳ لطفاً {wait_time} ثانیه صبر کنید", show_alert=True)
        return

    if data == "ignore":
        await bot.answer_callback_query(callback_query.id)
        return
    if data == "close":
        try:
            await callback_query.message.delete()
        except:
            pass
        return
    if data == "verify_membership":
        if INFO_CHANNEL_ID:
            is_member = await check_channel_membership(bot, user_id)
            if is_member:
                await bot.answer_callback_query(callback_query.id, "✅ عضویت شما تایید شد!", show_alert=True)
                await callback_query.message.delete()
                await bot.send_message(
                    chat_id,
                    f"✅ *عضویت شما با موفقیت تایید شد!*\n\n"
                    f"حالا می‌توانید از {BOT_NAME} استفاده کنید.\n"
                    f"کافیست نام آهنگ مورد نظر خود را بنویسید.{FOOTER}"
                )
            else:
                await bot.answer_callback_query(callback_query.id, "❌ هنوز عضو نشده‌اید!", show_alert=True)
        return

    try:
        parts = data.split(":")
        if data.startswith("page:search:"):
            search_id = parts[2]
            page = int(parts[3])
            await send_search_page(chat_id, search_id, page, callback_query.message)
        elif data.startswith("refine:"):
            entity = parts[1]
            term = parts[2]
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            if entity not in entity_map:
                await bot.send_message(chat_id, "نوع فیلتر نامعتبر است.")
                return
            status_msg = await bot.send_message(chat_id, f"🔍 *در حال جستجوی {entity} برای: {term}...*{FOOTER}")
            results = None
            if not OFFLINE_MODE:
                results = await search_itunes(term, entity=entity_map[entity], limit=50)
            if results is None:
                results = await local_search(term, entity)
            if results and results.get("resultCount", 0) > 0:
                search_id = generate_search_hash(entity, term)
                await set_cached(f"search:{search_id}", "search", {"type": entity, "term": term, "data": results})
                if not OFFLINE_MODE:
                    for item in results["results"]:
                        if item.get("wrapperType") == "artist":
                            await store_artist(item)
                        elif item.get("wrapperType") == "collection":
                            await store_album(item)
                        elif item.get("wrapperType") == "track":
                            await store_track(item)
                await status_msg.delete()
                await send_search_page(chat_id, search_id, 1, original_term=term)
            else:
                await status_msg.edit(f"❌ *نتیجه‌ای برای '{term}' در بخش {entity} یافت نشد.*{FOOTER}")
        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist(chat_id, artist_id, page, callback_query.message)
        elif data.startswith("album:"):
            album_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
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
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track(chat_id, track_id, callback_query.message)
        elif data.startswith("download:"):
            track_id = int(parts[1])
            await send_cached_or_download(bot, chat_id, track_id)
        elif data.startswith("preview:"):
            track_id = int(parts[1])
            await send_voice_preview(chat_id, track_id)
        elif data.startswith("recrawl:"):
            type_ = parts[1]
            id_ = int(parts[2])
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
        logger.error(f"Error handling callback {data}: {e}")


# ---------- Show functions (adapted for string path from download_audio) ----------
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
        text += f"*🔗 لینک آیتونز:* [مشاهده در آیتونز]({artist['artistLinkUrl']})\n"

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
        for i, album in enumerate(page_items, 1):
            btn_text = f"📀 {album.get('collectionName', 'نامشخص')[:45]}"
            markup.append([InlineKeyboardButton(text=btn_text, callback_data=f"album:{album['collectionId']}:1")])
        if total_pages > 1:
            pagination_row = create_pagination_row(f"artist:{artist_id}", page, total_pages)
            markup.append(pagination_row)

    markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])
    markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

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
        text += f"*🔗 لینک آیتونز:* [مشاهده در آیتونز]({album['collectionViewUrl']})\n"

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
                text=f"🎵 {track.get('trackName', 'نامشخص')[:40]} - {track.get('artistName', 'نامشخص')[:40]}",
                callback_data=f"track:{track['trackId']}")])
        if total_pages > 1:
            pagination_row = create_pagination_row(f"album:{album_id}", page, total_pages)
            markup.append(pagination_row)

    if album.get("artistId"):
        markup.append([InlineKeyboardButton(text="🎤 مشاهده هنرمند",
                                            callback_data=f"artist:{album['artistId']}:1")])
    markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:album:{album_id}")])
    markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

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
        links.append(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"album:{track['collectionId']}:1"))
    if track.get('artistId'):
        links.append(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"))
    markup.append(links)
    markup.append([InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}")])
    markup.append([InlineKeyboardButton(text="❌ بستن", callback_data="close")])

    text += FOOTER
    await status_msg.delete()

    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    await edit_or_send(bot, chat_id, message_to_edit, text, markup=InlineKeyboard(*markup), artwork_url=artwork_url)


if __name__ == "__main__":
    logger.info(f"🎵 {BOT_NAME} Music Bot Starting (with relational DB, rate limiting & broadcast)...")
    logger.info(f"Rate limit: {rate_limiter.max_requests} req/min per user")
    logger.info(f"Global rate limit: {rate_limiter.max_global} req/min")
    logger.info(f"Broadcast enabled for channel: {INFO_CHANNEL_ID}")
    bot.run()
