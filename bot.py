import logging
import json
import time
import asyncio
import hashlib
import os
import aiohttp
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

import yt_dlp
from ytmusicapi import YTMusic
from bale import Bot, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile

# ---------- Configuration ----------
ITUNES_BASE_URL = "https://itunes.apple.com"
DB_PATH = Path("cache.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1011430416:5JY8CU9nGwYtVz0ahfDEIkJyCkVTUCAhLXQ")
CACHE_CHANNEL_ID = os.environ.get("CACHE_CHANNEL_ID", None)  # set to your channel ID
ITEMS_PER_PAGE = 10
YT = None  # YTMusic instance initialized later

# ---------- Advanced Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("iTunesBot")

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
        # New table for audio cache channel mapping
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

# Audio cache (channel forwarding)
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
            await status_msg.edit("⏳ *در حال دریافت آلبوم‌های هنرمند...*")
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
            await status_msg.edit("⏳ *در حال دریافت اطلاعات هنرمند...*")
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
            await status_msg.edit("⏳ *در حال دریافت آهنگ‌های آلبوم...*")
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
            await status_msg.edit("⏳ *در حال دریافت اطلاعات آلبوم...*")
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
            await status_msg.edit("⏳ *در حال دریافت اطلاعات آهنگ...*")
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
        YT = YTMusic()  # requires no auth for search
    try:
        results = YT.search(query, filter="songs", limit=1)
        if results and isinstance(results, list) and len(results) > 0:
            return results[0].get("videoId")
    except Exception as e:
        logger.error(f"YTMusic search error: {e}")
    return None

# ---------- Download Logic ----------
async def download_and_send_track(bot: Bot, chat_id: int, video_url: str, track_title: str,
                                  artist_name: str, cover_url: str):
    temp_audio_file = f"temp_{chat_id}.mp3"
    status_msg = await bot.send_message(chat_id, "⏳ در حال دانلود و آماده‌سازی آهنگ...")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_audio_file.replace('.mp3', ''),
            'quiet': True,
            'cookiefile':'cookies.txt',
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: download_video(video_url, ydl_opts))
        # The output file will be temp_audio_file (with .mp3 extension after conversion)
        # Actual filename might be temp_audio_file itself
        if not os.path.exists(temp_audio_file):
            # yt-dlp might add .mp3 if outtmpl doesn't have extension?
            # Actually our outtmpl is temp_{chat_id} (no extension), then after extraction it becomes .mp3
            # So we should check temp_{chat_id}.mp3
            temp_audio_file = f"temp_{chat_id}.mp3"
            if not os.path.exists(temp_audio_file):
                raise FileNotFoundError("Downloaded file not found")

        cover_bytes = None
        if cover_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        cover_bytes = await resp.read()

        caption = f"🎵 {track_title}\n🎤 {artist_name}"
        with open(temp_audio_file, 'rb') as audio_file:
            audio_input = InputFile(audio_file, filename=f"{track_title}.mp3")
            if cover_bytes:
                thumb_input = InputFile(cover_bytes, filename="cover.jpg")
                await bot.send_audio(chat_id, audio=audio_input, caption=caption, thumb=thumb_input)
            else:
                await bot.send_audio(chat_id, audio=audio_input, caption=caption)
        await status_msg.edit("✅ آهنگ با موفقیت ارسال شد.")
    except Exception as e:
        logger.error(f"Download Error: {e}")
        await status_msg.edit("❌ خطا در دانلود یا استخراج آهنگ. لطفا دوباره تلاش کنید.")
    finally:
        if os.path.exists(temp_audio_file):
            os.remove(temp_audio_file)

def download_video(url, options):
    url = url.replace("music.","")
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except Exception as e:
        error_msg = str(e)
        if "Requested format is not available" in error_msg:
            logger.error(f"Format error for {url}. Fetching available formats list...")
            try:
                # Set up a new extractor without format limits to get all formats
                info_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'cookiefile': options.get('cookiefile')
                }
                with yt_dlp.YoutubeDL(info_opts) as ydl_info:
                    info = ydl_info.extract_info(url, download=False)
                    formats = info.get('formats', [])
                    
                    format_log = f"\n--- Available formats for {url} ---\n"
                    for f in formats:
                        fid = f.get('format_id', 'N/A')
                        ext = f.get('ext', 'N/A')
                        acodec = f.get('acodec', 'none')
                        vcodec = f.get('vcodec', 'none')
                        note = f.get('format_note', '')
                        format_log += f"ID: {fid:<5} | Ext: {ext:<4} | Acodec: {acodec:<10} | Vcodec: {vcodec:<10} | Note: {note}\n"
                    
                    logger.error(format_log)
            except Exception as extract_error:
                logger.error(f"Failed to extract format list: {extract_error}")
        
        # Re-raise the original exception so the rest of your error handling works
        raise e


async def send_cached_or_download(bot: Bot, chat_id: int, track_id: int):
    """Check audio cache channel, forward if exists; else download, upload to channel, store mapping."""
    # Get track info
    status_msg = await bot.send_message(chat_id, "⏳ *در حال آماده‌سازی دانلود...*")
    track_data = await get_track(track_id, status_msg)
    if not track_data or not track_data.get("results"):
        await status_msg.edit("❌ خطا در دریافت اطلاعات آهنگ.")
        return
    track = track_data["results"][0]
    t_name = track.get("trackName", "")
    a_name = track.get("artistName", "")
    cover_url = get_high_res_artwork(track.get("artworkUrl100"))

    # Check if already cached in channel
    channel_msg_id = await get_audio_cache(track_id)
    if channel_msg_id and CACHE_CHANNEL_ID:
        try:
            await bot.forward_message(chat_id, from_chat_id=CACHE_CHANNEL_ID, message_id=channel_msg_id)
            await status_msg.edit("✅ آهنگ از حافظه کش ارسال شد.")
            return
        except Exception as e:
            logger.error(f"Forward failed: {e}, will re-download")

    # Need to download and upload
    query = f"{t_name} {a_name}"
    video_id = await search_youtube_track(query)
    if not video_id:
        await status_msg.edit("❌ نتوانستیم لینک یوتیوب موزیک را پیدا کنیم.")
        return
    video_url = f"https://music.youtube.com/watch?v={video_id}"
    # Download and send to user
    await download_and_send_track(bot, chat_id, video_url, t_name, a_name, cover_url)
    # Upload to cache channel if configured
    if CACHE_CHANNEL_ID:
        try:
            # Re-send to cache channel and store mapping
            # To avoid duplicate download, we can re-use the audio file we just sent? Not easily.
            # Simplest: We'll do the download again for channel? Could forward from user chat to channel but
            # that would require the user's message. Better to have a separate function to upload to channel.
            # For simplicity, we'll just re-download and send to channel, store mapping.
            # To optimize, we could keep the temp file but it's already deleted. So re-download.
            logger.info(f"Uploading to cache channel for track {track_id}")
            # Re-download and send to channel
            temp_file = f"cache_{track_id}.mp3"
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_file.replace('.mp3', ''),
            'cookiefile':'cookies.txt',
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: download_video(video_url, ydl_opts))
            temp_file = f"cache_{track_id}.mp3"
            if os.path.exists(temp_file):
                with open(temp_file, 'rb') as f:
                    sent_msg = await bot.send_audio(CACHE_CHANNEL_ID, audio=InputFile(f, filename=f"{t_name}.mp3"),
                                                    caption=f"🎵 {t_name}\n🎤 {a_name}")
                    if sent_msg and sent_msg.message_id:
                        await set_audio_cache(track_id, sent_msg.message_id)
                os.remove(temp_file)
        except Exception as e:
            logger.error(f"Failed to cache audio in channel: {e}")

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

# ---------- Bale Bot ----------
bot = Bot(token=BOT_TOKEN)

@bot.event
async def on_ready():
    logger.info(f"{bot.user.username} is ready and connected to Bale!")
    await bot.delete_webhook()
    await init_db()

@bot.event
async def on_message(message: Message):
    if not message.content:
        return
    if message.content.startswith("/start"):
        await message.reply(
            "🎵 *به ربات جستجوی موسیقی iTunes خوش آمدید!*\n\n"
            "*دستورات:*\n"
            "`/search artist:<نام>` - جستجوی هنرمند\n"
            "`/search album:<نام>` - جستجوی آلبوم\n"
            "`/search track:<نام>` - جستجوی آهنگ\n"
            "`/search <نام>` - جستجوی ترکیبی (همه موارد)\n\n"
            "*ویژگی‌ها:*\n"
            "• کش شدن هوشمند اطلاعات\n"
            "• پخش پیش‌نمایش صوتی آهنگ‌ها\n"
            "• دریافت کاور اورجینال با کیفیت بالا\n"
            "• دانلود مستقیم آهنگ از یوتیوب موزیک\n"
            "• جستجوی ترکیبی بدون فیلتر"
        )
    elif message.content.startswith("/search"):
        parts = message.content.split(" ", 1)
        if len(parts) < 2:
            await message.reply("❌ *لطفاً عبارت جستجو را وارد کنید.*\nمثال: `/search artist:Taylor Swift` یا `/search hello`")
            return
        query = parts[1].strip()
        if ":" in query:
            type_, term = query.split(":", 1)
            type_ = type_.lower()
            if type_ not in ["artist", "album", "track"]:
                await message.reply("❌ *نوع جستجو نامعتبر است.*\nیکی از گزینه‌های `artist`, `album`, `track` را انتخاب کنید.")
                return
        else:
            type_ = "all"
            term = query

        entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "all": "همه"}
        status_msg = await message.reply(f"🔍 *در حال جستجوی {type_fa_map[type_]}: {term}...*")

        search_id = generate_search_hash(type_, term)
        cache_key = f"search:{search_id}"

        if type_ == "all":
            results = await search_itunes(term, entity=None, limit=50)
        else:
            results = await search_itunes(term, entity_map[type_], limit=50)

        if results and results.get("resultCount", 0) > 0:
            await set_cached(cache_key, "search", {"type": type_, "term": term, "data": results})
        else:
            await status_msg.edit(f"❌ *هیچ نتیجه‌ای برای '{term}' یافت نشد.*")
            return

        await status_msg.delete()
        await send_search_page(message.chat.id, search_id, 1)

async def send_search_page(chat_id: int, search_id: str, page: int, message_to_edit: Message = None):
    cache_key = f"search:{search_id}"
    cache_data = await get_cached(cache_key)
    if not cache_data:
        text = "❌ خطایی در بارگذاری نتایج رخ داد (احتمالا سشن منقضی شده است)."
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

    text = header
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
                               "🔍 لطفاً عبارت جستجوی خود را با فرمت زیر وارد کنید:\n`/search <نوع:>عبارت`\nمثلاً `/search artist:ed sheeran` یا `/search hello`")
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
                await bot.send_message(chat_id, "❌ هنرمند یافت نشد.")
                return
            artist_name = artist_data["results"][0].get("artistName", "نامشخص")
            # Perform search for tracks by this artist name
            search_id = generate_search_hash("track", artist_name)
            cache_key = f"search:{search_id}"
            results = await search_itunes(artist_name, entity="musicTrack", limit=50)
            if results and results.get("resultCount", 0) > 0:
                await set_cached(cache_key, "search", {"type": "track", "term": artist_name, "data": results})
                await send_search_page(chat_id, search_id, page, callback.message)
            else:
                await bot.send_message(chat_id, "❌ هیچ آهنگی برای این هنرمند یافت نشد.")

    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")

async def show_artist(chat_id: int, artist_id: int, page: int = 1, message_to_edit: Message = None):
    status_msg = await bot.send_message(chat_id, "🔄 *در حال پردازش هنرمند...*")
    data = await get_artist(artist_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit("❌ *هنرمند یافت نشد.*")
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

    # Add tracks button for artist
    artist_name = artist.get("artistName", "")
    markup.add(InlineKeyboardButton(text="🎵 مشاهده آهنگ‌های هنرمند",
                                    callback_data=f"artist_tracks:{artist_id}:1"), row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}"),
               row=bottom_row + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 2)

    await status_msg.delete()
    if message_to_edit:
        try:
            await message_to_edit.edit(text, components=markup)
        except:
            await bot.send_message(chat_id, text, components=markup)
    else:
        await bot.send_message(chat_id, text, components=markup)

async def show_album(chat_id: int, album_id: int, page: int = 1, message_to_edit: Message = None):
    status_msg = await bot.send_message(chat_id, "🔄 *در حال پردازش آلبوم...*")
    data = await get_album(album_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit("❌ *آلبوم یافت نشد.*")
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

    # Add artist button
    if album.get("artistId"):
        markup.add(InlineKeyboardButton(text="🎤 مشاهده هنرمند",
                                        callback_data=f"artist:{album['artistId']}:1"), row=bottom_row)
        bottom_row += 1
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:album:{album_id}"),
               row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 1)

    await status_msg.delete()
    artwork_url = get_high_res_artwork(album.get("artworkUrl100"))
    sent_photo = False
    if artwork_url:
        try:
            # Download image bytes and use InputFile to avoid "photo param must be type of InputFile"
            async with aiohttp.ClientSession() as session:
                async with session.get(artwork_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        photo_input = InputFile(img_bytes, filename="cover.jpg")
                        if message_to_edit:
                            # Cannot edit with photo easily, so send new message and delete old?
                            # Simpler: delete old message, send new photo
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
    status_msg = await bot.send_message(chat_id, "🔄 *در حال بارگذاری اطلاعات آهنگ...*")
    data = await get_track(track_id, status_msg)
    if not data or not data.get("results"):
        await status_msg.edit("❌ *آهنگ یافت نشد.*")
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
    markup.add(InlineKeyboardButton(text="⬇️ دانلود کامل آهنگ", callback_data=f"download:{track_id}"), row=1)
    row = 2
    if track.get('collectionId'):
        markup.add(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"album:{track['collectionId']}:1"), row=row)
    if track.get('artistId'):
        markup.add(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"), row=row)
    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}"), row=row + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=row + 2)

    await status_msg.delete()

    # Send cover photo as InputFile
    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    sent_photo = False
    if artwork_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(artwork_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        photo_input = InputFile(img_bytes, filename="cover.jpg")
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

    # Send preview audio
    preview_url = track.get("previewUrl")
    if preview_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(preview_url) as resp:
                    if resp.status == 200:
                        audio_bytes = await resp.read()
                        audio_input = InputFile(audio_bytes, filename="preview.m4a")
                        await bot.send_audio(chat_id, audio=audio_input, caption="🎧 پیش‌نمایش صوتی ۳۰ ثانیه‌ای")
        except Exception as e:
            logger.error(f"Failed to send audio preview: {e}")

if __name__ == "__main__":
    logger.info("🎵 iTunes Music Bot Starting...")
    bot.run()
