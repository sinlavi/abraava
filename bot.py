"""
bale_music_bot.py
Abraava Music Bot with advanced 8‑method YouTube Music downloader, metadata tagging, and caching.
"""

import logging
import json
import time
import asyncio
import hashlib
import os
import sys
import aiohttp
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

import yt_dlp
from ytmusicapi import YTMusic
from bale import Bot, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, error

# Import the 8‑method downloader
from youtube_downloader import download_audio

# ---------- Configuration ----------
ITUNES_BASE_URL = "https://itunes.apple.com"
DB_PATH = Path("cache.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1011430416:5JY8CU9nGwYtVz0ahfDEIkJyCkVTUCAhLXQ")
DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID", None)  # Github Secret: DB_CHANNEL_ID
ITEMS_PER_PAGE = 10
YT = None  # YTMusic instance initialized later

# ---------- Bot Information ----------
BOT_NAME = "ابرآوا"
FOOTER = "\n\n@abraava_bot\n@abraava"

# ---------- Advanced Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AbraavaBot")

# ---------- Async SQLite Cache ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                last_updated INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audio_cache (
                track_id INTEGER PRIMARY KEY,
                channel_message_id INTEGER NOT NULL
            )
        """)
        await db.commit()
    logger.info("Database initialized successfully.")

async def get_cached(id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM cache WHERE id = ?", (id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
    return None

async def set_cached(id: str, type: str, data: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO cache (id, type, data, last_updated)
            VALUES (?, ?, ?, ?)
        """, (id, type, json.dumps(data), int(time.time())))
        await db.commit()

async def delete_cached(id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cache WHERE id = ?", (id,))
        await db.commit()

async def is_cached(id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM cache WHERE id = ?", (id,)) as cursor:
            return await cursor.fetchone() is not None

async def get_audio_cache(track_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_message_id FROM audio_cache WHERE track_id = ?", (track_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_audio_cache(track_id: int, channel_message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO audio_cache (track_id, channel_message_id) VALUES (?, ?)",
                         (track_id, channel_message_id))
        await db.commit()

# ---------- Shared HTTP Session ----------
class HttpClient:
    session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_session(cls):
        if cls.session is None or cls.session.closed:
            connector = aiohttp.TCPConnector()
            cls.session = aiohttp.ClientSession(connector=connector)
        return cls.session

    @classmethod
    async def close(cls):
        if cls.session and not cls.session.closed:
            await cls.session.close()

# ---------- iTunes API Client ----------
async def fetch_itunes(endpoint: str, params: dict) -> Optional[Dict[str, Any]]:
    session = await HttpClient.get_session()
    url = f"{ITUNES_BASE_URL}/{endpoint}"
    try:
        async with session.get(url, params=params, ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON from {url}")
                    return None
            else:
                logger.warning(f"iTunes API returned status {resp.status} for {url}")
    except Exception as e:
        logger.error(f"Error fetching from iTunes API ({endpoint}): {e}")
    return None

async def search_itunes(term: str, entity: Optional[str] = None, limit: int = 50) -> Optional[Dict[str, Any]]:
    logger.info(f"Searching iTunes: term='{term}', entity='{entity}'")
    params = {"term": term, "media": "music", "limit": limit, "country": "US"}
    if entity:
        params["entity"] = entity
    return await fetch_itunes("search", params)

async def lookup_itunes(id: int, entity: Optional[str] = None) -> Optional[Dict[str, Any]]:
    logger.info(f"Looking up iTunes: id={id}, entity={entity}")
    params = {"id": id, "country": "US"}
    if entity:
        params["entity"] = entity
    return await fetch_itunes("lookup", params)

# ---------- Crawlers ----------
async def crawl_artist_albums(artist_id: int, status_msg: Message = None):
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
                album_cache_id = f"album:{album_id}"
                if not await is_cached(album_cache_id):
                    await set_cached(album_cache_id, "album", {"resultCount": 1, "results": [item]})
        await set_cached(cache_id, "artist_albums", {"albums": albums})

async def get_artist(artist_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    cache_id = f"artist:{artist_id}"
    cached = await get_cached(cache_id)
    if cached:
        return cached
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات هنرمند...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(artist_id)
    if data and data.get("results"):
        await set_cached(cache_id, "artist", data)
        await crawl_artist_albums(artist_id, status_msg)
        return data
    return None

async def crawl_album_tracks(album_id: int, status_msg: Message = None):
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
                track_cache_id = f"track:{track_id}"
                if not await is_cached(track_cache_id):
                    await set_cached(track_cache_id, "track", {"resultCount": 1, "results": [item]})
        await set_cached(cache_id, "album_tracks", {"tracks": tracks})

async def get_album(album_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    cache_id = f"album:{album_id}"
    cached = await get_cached(cache_id)
    if cached:
        return cached
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آلبوم...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(album_id)
    if data and data.get("results"):
        await set_cached(cache_id, "album", data)
        await crawl_album_tracks(album_id, status_msg)
        return data
    return None

async def get_track(track_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    cache_id = f"track:{track_id}"
    cached = await get_cached(cache_id)
    if cached:
        return cached
    if status_msg:
        try:
            await status_msg.edit(f"⏳ *در حال دریافت اطلاعات آهنگ...*{FOOTER}")
        except:
            pass
    data = await lookup_itunes(track_id)
    if data and data.get("results"):
        await set_cached(cache_id, "track", data)
        return data
    return None

# ---------- YouTube Music Helper ----------
async def search_youtube_track(query: str) -> Optional[str]:
    """Search YouTube Music and return best video ID."""
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

# ---------- Metadata Tagger ----------
def tag_mp3(file_path: Path, title: str, artist: str, album: str, cover_bytes: bytes):
    """Add ID3 metadata to the downloaded MP3 file."""
    try:
        try:
            audio = ID3(file_path)
        except error:
            audio = ID3()
        
        audio.add(TIT2(encoding=3, text=title))
        audio.add(TPE1(encoding=3, text=artist))
        if album:
            audio.add(TALB(encoding=3, text=album))
        if cover_bytes:
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=cover_bytes
            ))
        audio.save(file_path, v2_version=3)
        logger.info(f"Metadata updated successfully for {title}")
    except Exception as e:
        logger.error(f"Failed to tag MP3 {file_path}: {e}")

# ---------- Download & Caching Logic ----------
async def send_cached_or_download(bot: Bot, chat_id: int, track_id: int):
    status_msg = await bot.send_message(chat_id, f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*{FOOTER}")
    
    # Check if already cached in DB Channel
    channel_msg_id = await get_audio_cache(track_id)
    if channel_msg_id and DB_CHANNEL_ID:
        try:
            # Forward directly from database channel to the user
            await bot.forward_message(chat_id, from_chat_id=DB_CHANNEL_ID, message_id=channel_msg_id)
            await status_msg.edit(f"✅ آهنگ با موفقیت از دیتابیس {BOT_NAME} دریافت شد.{FOOTER}")
            return
        except Exception as e:
            logger.error(f"Forward failed: {e}, will re-download")

    # If not cached, fetch track info for downloading
    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await status_msg.edit(f"❌ خطا در دریافت اطلاعات آهنگ.{FOOTER}")
        return
    
    track = track_data["results"][0]
    t_name = track.get("trackName", "Unknown Title")
    a_name = track.get("artistName", "Unknown Artist")
    album_name = track.get("collectionName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100"), size=600)

    query = f"{t_name} {a_name}"
    await status_msg.edit(f"🔍 جستجوی سورس باکیفیت آهنگ در یوتیوب موزیک...{FOOTER}")
    
    video_id = await search_youtube_track(query)
    if not video_id:
        await status_msg.edit(f"❌ نتوانستیم لینک یوتیوب موزیک را برای این آهنگ پیدا کنیم.{FOOTER}")
        return
    video_url = f"https://music.youtube.com/watch?v={video_id}"

    await status_msg.edit(f"⏳ در حال دانلود و آماده‌سازی آهنگ (روش‌های پیشرفته ضد تحریم)...{FOOTER}")

    try:
        mp3_path = await asyncio.get_event_loop().run_in_executor(
            None, download_audio, video_url
        )

        if mp3_path is None:
            await status_msg.edit(f"❌ دانلود با شکست مواجه شد — همه ۸ روش ناموفق بودند.{FOOTER}")
            return

        file_size_mb = mp3_path.stat().st_size / (1024 * 1024)

        # Download cover image
        cover_bytes = None
        if cover_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        cover_bytes = await resp.read()

        # Update metadata using mutagen
        await asyncio.get_event_loop().run_in_executor(
            None, tag_mp3, mp3_path, t_name, a_name, album_name, cover_bytes
        )

        caption = f"🎵 {t_name}\n🎤 {a_name}\n📀 {album_name}\n🔊 MP3 320 kbps | {file_size_mb:.1f} MB{FOOTER}"

        # Upload the tagged file to the DB_CHANNEL_ID first (if exists)
        if DB_CHANNEL_ID:
            try:
                await status_msg.edit(f"☁️ در حال آپلود در سرورهای ابری {BOT_NAME}...{FOOTER}")
                with open(mp3_path, "rb") as f:
                    audio_bytes = f.read()
                
                audio_input = InputFile(audio_bytes, file_name=f"{t_name} - {a_name}.mp3")
                db_msg = await bot.send_audio(
                    6053683389,
                    audio=audio_input,
                    caption=caption
                )
                
                if db_msg and db_msg.message_id:
                    # Cache successful, save ID
                    await set_audio_cache(track_id, db_msg.message_id)
                    # Forward to User
                    await bot.forward_message(chat_id, from_chat_id=DB_CHANNEL_ID, message_id=db_msg.message_id)
                    await status_msg.edit(f"✅ دانلود و پردازش با موفقیت انجام شد.{FOOTER}")
            except Exception as e:
                logger.error(f"Error caching to DB_CHANNEL: {e}")
                # Fallback: Send directly to user if DB Channel upload fails
                with open(mp3_path, "rb") as f:
                    audio_bytes = f.read()
                audio_input = InputFile(audio_bytes, file_name=f"{t_name} - {a_name}.mp3")
                await bot.send_audio(chat_id, audio=audio_input, caption=caption)
                await status_msg.edit(f"✅ آهنگ مستقیما ارسال شد (خطا در ذخیره دیتابیس).{FOOTER}")
        else:
            # If no DB_CHANNEL_ID is configured, send directly to user
            with open(mp3_path, "rb") as f:
                audio_bytes = f.read()
            audio_input = InputFile(audio_bytes, file_name=f"{t_name} - {a_name}.mp3")
            await bot.send_audio(chat_id, audio=audio_input, caption=caption)
            await status_msg.edit(f"✅ دانلود و ارسال با موفقیت انجام شد.{FOOTER}")

        # Clean up temp file
        mp3_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Download error")
        await status_msg.edit(f"❌ خطا در عملیات: {e}{FOOTER}")

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
        async with aiohttp.ClientSession() as session:
            async with session.get(preview_url) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    voice_input = InputFile(audio_bytes, file_name="preview.m4a")
                    await bot.send_audio(chat_id, audio=voice_input, caption=f"🎧 پیش‌نمایش صوتی آهنگ {track.get('trackName')}{FOOTER}")
                    await status_msg.delete()
                else:
                    await status_msg.edit(f"❌ خطا در ارتباط با سرور آیتیونز.{FOOTER}")
    except Exception as e:
        logger.error(f"Failed to send audio preview: {e}")
        await status_msg.edit(f"❌ خطا در ارسال پیش‌نمایش.{FOOTER}")


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
        row.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"{callback_prefix}:{current_page - 1}"))
    row.append(InlineKeyboardButton(text=f"صفحه {current_page} از {total_pages}", callback_data="ignore"))
    if current_page < total_pages:
        row.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"{callback_prefix}:{current_page + 1}"))
    return row

def generate_search_hash(type_: str, term: str) -> str:
    return hashlib.md5(f"{type_}:{term}".encode()).hexdigest()[:10]

# ---------- Bale Bot Initialization & Handlers ----------
bot = Bot(token=BOT_TOKEN)

@bot.event
async def on_ready():
    logger.info(f"{bot.user.username} (Abraava) is ready and connected to Bale!")
    await bot.delete_webhook()
    await init_db()

@bot.event
async def on_message(message: Message):
    if not message.content:
        return

    # Handle Group / Channel tagging logic
    is_group = message.chat.type in ["group", "supergroup", "channel"]
    msg_text = message.content

    if is_group:
        bot_mention = f"@{bot.user.username}"
        if bot_mention not in msg_text:
            return  # Ignore messages in groups if bot is not explicitly mentioned
        msg_text = msg_text.replace(bot_mention, "").strip()
    
    # Command Handlers
    if msg_text.startswith("/start"):
        await message.reply(
            f"🎵 *به ربات جستجو و دانلود موسیقی {BOT_NAME} خوش آمدید!*\n\n"
            "*دستورات:*\n"
            "`/search artist:<نام>` - جستجوی هنرمند\n"
            "`/search album:<نام>` - جستجوی آلبوم\n"
            "`/search track:<نام>` - جستجوی آهنگ\n"
            "`/search <نام>` - جستجوی ترکیبی\n\n"
            "*ویژگی‌ها:*\n"
            "• کش شدن و دیتابیس اختصاصی (ارسال فوری)\n"
            "• ثبت خودکار متادیتا (کاور، نام و خواننده) روی آهنگ\n"
            "• پخش پیش‌نمایش صوتی با لمس دکمه\n"
            "• دانلود سورس اورجینال از یوتیوب موزیک (ضد تحریم)\n"
            "  🔊 MP3 320 kbps | ۸ روش عبور از تشخیص ربات"
            f"{FOOTER}"
        )
    elif msg_text.startswith("/help"):
        await message.reply(
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            "برای جستجوی موزیک کافیست از دستور `/search` استفاده کنید.\n"
            "مثال: `/search ed sheeran`\n\n"
            "⚠️ اگر می‌خواهید ربات را در گروه‌ها استفاده کنید، حتما باید آیدی ربات را تگ کنید:\n"
            f"`@{bot.user.username} /search hello`"
            f"{FOOTER}"
        )
    elif msg_text.startswith("/about"):
        await message.reply(
            f"ℹ️ *درباره ربات {BOT_NAME}*\n\n"
            f"این ربات یک دستیار هوشمند برای جستجو در دیتابیس عظیم iTunes و دانلود باکیفیت‌ترین سورس موجود از YouTube Music به صورت ضدتحریم می‌باشد.\n"
            f"تمامی آهنگ‌ها پیش از ارسال توسط سرورهای ما پردازش و تگ‌گذاری (کاور و اطلاعات) می‌شوند."
            f"{FOOTER}"
        )
    elif msg_text.startswith("/setting"):
        await message.reply(
            f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
            "در حال حاضر تنظیمات خاصی برای پیکربندی وجود ندارد و ربات در بهترین حالت کیفی (MP3 320kbps) تنظیم شده است."
            f"{FOOTER}"
        )
    elif msg_text.startswith("/search"):
        parts = msg_text.split(" ", 1)
        if len(parts) < 2:
            await message.reply(f"❌ *لطفاً عبارت جستجو را وارد کنید.*\nمثال: `/search artist:Taylor Swift` یا `/search hello`{FOOTER}")
            return
        query = parts[1].strip()
        if ":" in query:
            type_, term = query.split(":", 1)
            type_ = type_.lower()
            if type_ not in ["artist", "album", "track"]:
                await message.reply(f"❌ *نوع جستجو نامعتبر است.*\nیکی از گزینه‌های `artist`, `album`, `track` را انتخاب کنید.{FOOTER}")
                return
        else:
            type_ = "all"
            term = query

        entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "all": "همه"}
        status_msg = await message.reply(f"🔍 *در حال جستجوی {type_fa_map[type_]}: {term}...*{FOOTER}")

        search_id = generate_search_hash(type_, term)
        cache_key = f"search:{search_id}"

        if type_ == "all":
            results = await search_itunes(term, entity=None, limit=50)
        else:
            results = await search_itunes(term, entity_map[type_], limit=50)

        if results and results.get("resultCount", 0) > 0:
            await set_cached(cache_key, "search", {"type": type_, "term": term, "data": results})
        else:
            await status_msg.edit(f"❌ *هیچ نتیجه‌ای برای '{term}' یافت نشد.*{FOOTER}")
            return

        await status_msg.delete()
        await send_search_page(message.chat.id, search_id, 1)

async def send_search_page(chat_id: int, search_id: str, page: int, message_to_edit: Message = None):
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

    markup = InlineKeyboardMarkup()
    if type_ == "all":
        header = f"📋 *نتایج جستجوی ترکیبی برای: {term}*\nتعداد کل: {total_items} مورد"
    else:
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}
        header = f"📋 *نتایج جستجو برای {type_fa_map[type_]}: {term}*\nتعداد کل: {total_items} مورد"

    for i, item in enumerate(page_items, 1):
        if type_ == "all":
            wrapper = item.get("wrapperType")
            if wrapper == "artist":
                btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
                callback = f"artist:{item['artistId']}:1"
            elif wrapper == "collection":
                btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:45]}"
                callback = f"album:{item['collectionId']}:1"
            elif wrapper == "track":
                btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:45]}"
                callback = f"track:{item['trackId']}"
            else:
                continue
        else:
            if type_ == "artist":
                btn_text = f"🎤 {item.get('artistName', 'نامشخص')}"
                callback = f"artist:{item['artistId']}:1"
            elif type_ == "album":
                btn_text = f"📀 {item.get('collectionName', 'نامشخص')[:45]}"
                callback = f"album:{item['collectionId']}:1"
            elif type_ == "track":
                btn_text = f"🎵 {item.get('trackName', 'نامشخص')[:45]}"
                callback = f"track:{item['trackId']}"
        markup.add(InlineKeyboardButton(text=btn_text, callback_data=callback), row=i)

    if total_pages > 1:
        pagination_row = create_pagination_row(f"page:search:{search_id}", page, total_pages)
        for btn in pagination_row:
            markup.add(btn, row=len(page_items) + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=len(page_items) + 2)

    text = header + FOOTER
    if message_to_edit:
        try:
            await message_to_edit.edit(text, components=markup)
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            await bot.send_message(chat_id, text, components=markup)
    else:
        await bot.send_message(chat_id, text, components=markup)

@bot.event
async def on_callback(callback: CallbackQuery):
    data = callback.data
    chat_id = callback.message.chat.id
    logger.info(f"Callback received: {data} from user {chat_id}")
    if data == "ignore":
        return
    if data == "new_search":
        await bot.send_message(chat_id,
                               f"🔍 لطفاً عبارت جستجوی خود را با فرمت زیر وارد کنید:\n`/search <نوع:>عبارت`\nمثلاً `/search artist:ed sheeran` یا `/search hello`{FOOTER}")
        return
    try:
        parts = data.split(":")
        if data.startswith("page:search:"):
            search_id = parts[2]
            page = int(parts[3])
            await send_search_page(chat_id, search_id, page, callback.message)

        elif data.startswith("artist:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_artist(chat_id, artist_id, page, callback.message)

        elif data.startswith("album:"):
            album_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            await show_album(chat_id, album_id, page, callback.message)

        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track(chat_id, track_id)

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
                await delete_cached(f"artist:{id_}")
                await delete_cached(f"artist_albums:{id_}")
                await show_artist(chat_id, id_, 1, callback.message)
            elif type_ == "album":
                await delete_cached(f"album:{id_}")
                await delete_cached(f"album_tracks:{id_}")
                await show_album(chat_id, id_, 1, callback.message)
            elif type_ == "track":
                await delete_cached(f"track:{id_}")
                await show_track(chat_id, id_, callback.message)

        elif data.startswith("artist_tracks:"):
            artist_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            artist_data = await get_artist(artist_id)
            if not artist_data or not artist_data.get("results"):
                await bot.send_message(chat_id, f"❌ هنرمند یافت نشد.{FOOTER}")
                return
            artist_name = artist_data["results"][0].get("artistName", "نامشخص")
            search_id = generate_search_hash("track", artist_name)
            cache_key = f"search:{search_id}"
            results = await search_itunes(artist_name, entity="musicTrack", limit=50)
            if results and results.get("resultCount", 0) > 0:
                await set_cached(cache_key, "search", {"type": "track", "term": artist_name, "data": results})
                await send_search_page(chat_id, search_id, page, callback.message)
            else:
                await bot.send_message(chat_id, f"❌ هیچ آهنگی برای این هنرمند یافت نشد.{FOOTER}")

    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")

async def show_artist(chat_id: int, artist_id: int, page: int = 1, message_to_edit: Message = None):
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
            album_data = await get_cached(f"album:{album_id}")
            if album_data and album_data.get("results"):
                albums.append(album_data["results"][0])

    markup = InlineKeyboardMarkup()
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
            markup.add(InlineKeyboardButton(text=btn_text, callback_data=f"album:{album['collectionId']}:1"), row=i)
        if total_pages > 1:
            pagination_row = create_pagination_row(f"artist:{artist_id}", page, total_pages)
            for btn in pagination_row:
                markup.add(btn, row=len(page_items) + 1)
        bottom_row = len(page_items) + 2
    else:
        bottom_row = 1

    artist_name = artist.get("artistName", "")
    markup.add(InlineKeyboardButton(text="🎵 مشاهده آهنگ‌های هنرمند",
                                    callback_data=f"artist_tracks:{artist_id}:1"), row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}"),
               row=bottom_row + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 2)

    text += FOOTER
    await status_msg.delete()
    if message_to_edit:
        try:
            await message_to_edit.edit(text, components=markup)
        except:
            await bot.send_message(chat_id, text, components=markup)
    else:
        await bot.send_message(chat_id, text, components=markup)

async def show_album(chat_id: int, album_id: int, page: int = 1, message_to_edit: Message = None):
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
            track_data = await get_cached(f"track:{track_id}")
            if track_data and track_data.get("results"):
                tracks.append(track_data["results"][0])

    markup = InlineKeyboardMarkup()
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
            text += f"`{i}.` {track.get('trackName', 'نامشخص')} ({duration})\n"
        for i, track in enumerate(page_items, 1):
            markup.add(InlineKeyboardButton(text=f"🎵 {track.get('trackName', 'نامشخص')[:40]}",
                                            callback_data=f"track:{track['trackId']}"), row=i)
        if total_pages > 1:
            pagination_row = create_pagination_row(f"album:{album_id}", page, total_pages)
            for btn in pagination_row:
                markup.add(btn, row=len(page_items) + 1)
        bottom_row = len(page_items) + 2
    else:
        bottom_row = 1

    if album.get("artistId"):
        markup.add(InlineKeyboardButton(text="🎤 مشاهده هنرمند",
                                        callback_data=f"artist:{album['artistId']}:1"), row=bottom_row)
        bottom_row += 1
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:album:{album_id}"),
               row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 1)

    text += FOOTER
    await status_msg.delete()
    artwork_url = get_high_res_artwork(album.get("artworkUrl100"))
    sent_photo = False
    if artwork_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(artwork_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        photo_input = InputFile(img_bytes, file_name="cover.jpg")
                        if message_to_edit:
                            await message_to_edit.delete()
                        await bot.send_photo(chat_id, photo=photo_input, caption=text, components=markup)
                        sent_photo = True
        except Exception as e:
            logger.error(f"Failed to send album cover photo: {e}")

    if not sent_photo:
        if message_to_edit:
            try:
                await message_to_edit.edit(text, components=markup)
            except:
                await bot.send_message(chat_id, text, components=markup)
        else:
            await bot.send_message(chat_id, text, components=markup)

async def show_track(chat_id: int, track_id: int, message_to_edit: Message = None):
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

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="⬇️ دانلود کامل آهنگ (320 kbps)", callback_data=f"download:{track_id}"), row=1)
    
    row = 2
    # Add Preview button ONLY if previewUrl exists
    if track.get("previewUrl"):
        markup.add(InlineKeyboardButton(text="🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"), row=row)
        row += 1

    if track.get('collectionId'):
        markup.add(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"album:{track['collectionId']}:1"), row=row)
    if track.get('artistId'):
        markup.add(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"), row=row)
    
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}"), row=row + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=row + 2)

    text += FOOTER
    await status_msg.delete()

    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    sent_photo = False
    if artwork_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(artwork_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        photo_input = InputFile(img_bytes, file_name="cover.jpg")
                        if message_to_edit:
                            await message_to_edit.delete()
                        await bot.send_photo(chat_id, photo=photo_input, caption=text, components=markup)
                        sent_photo = True
        except Exception as e:
            logger.error(f"Failed to send track cover: {e}")

    if not sent_photo:
        if message_to_edit:
            try:
                await message_to_edit.edit(text, components=markup)
            except:
                await bot.send_message(chat_id, text, components=markup)
        else:
            await bot.send_message(chat_id, text, components=markup)


if __name__ == "__main__":
    logger.info(f"🎵 {BOT_NAME} Music Bot Starting (with anti‑detection & tagging)...")
    bot.run()
