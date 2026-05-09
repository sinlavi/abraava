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
BOT_TOKEN = '1011430416:5JY8CU9nGwYtVz0ahfDEIkJyCkVTUCAhLXQ'
ITEMS_PER_PAGE = 10  # 10 results per page (max 50 total)

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
        try:
            await db.execute("SELECT id, type, data, last_updated FROM cache LIMIT 1")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    last_updated INTEGER NOT NULL
                )
            """)
        except aiosqlite.OperationalError:
            logger.warning("Database structure mismatch or missing. Recreating 'cache' table...")
            await db.execute("DROP TABLE IF EXISTS cache")
            await db.execute("""
                CREATE TABLE cache (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    last_updated INTEGER NOT NULL
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
                    # Added resultCount to prevent "not found" error
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
                    # Added resultCount to prevent "not found" error
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


# ---------- YouTube Download Logic ----------

async def download_and_send_track(bot, chat_id, video_url, track_title, artist_name, cover_url):
    temp_audio_file = f"temp_{chat_id}.mp3"
    
    # پیام در حال پردازش
    status_msg = await bot.send_message(chat_id, "⏳ در حال دانلود و آماده‌سازی آهنگ...")

    try:
        # 1. تنظیمات بهینه‌شده yt-dlp
        ydl_opts = {
            'format': 'bestaudio/best', # انتخاب بهترین کیفیت صدای موجود
            'outtmpl': temp_audio_file.replace('.mp3', ''), # نام فایل خروجی
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        # دانلود آهنگ
        with YoutubeDL(ydl_opts) as ydl:
            # yt-dlp به صورت خودکار پسوند .mp3 را بعد از تبدیل اضافه میکند
            ydl.download([video_url])

        # 2. دانلود کاور آهنگ در حافظه برای ارسال در بله
        cover_bytes = None
        if cover_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        cover_bytes = await resp.read()

        # 3. ارسال فایل صوتی به همراه کاور
        caption = f"🎵 {track_title}\n🎤 {artist_name}"
        
        with open(temp_audio_file, 'rb') as audio_file:
            audio_input = InputFile(audio_file, filename=f"{track_title}.mp3")
            
            if cover_bytes:
                # اگر کاور با موفقیت دانلود شد
                thumb_input = InputFile(cover_bytes, filename="cover.jpg")
                await bot.send_audio(
                    chat_id, 
                    audio=audio_input, 
                    caption=caption,
                    thumb=thumb_input # ارسال عکس به عنوان تامنیل/کاور
                )
            else:
                # اگر کاور در دسترس نبود، فقط آهنگ را بفرست
                await bot.send_audio(
                    chat_id, 
                    audio=audio_input, 
                    caption=caption
                )

        await status_msg.edit_text("✅ آهنگ با موفقیت ارسال شد.")

    except Exception as e:
        print(f"Download Error: {e}")
        await status_msg.edit_text("❌ خطا در دانلود یا استخراج آهنگ. لطفا دوباره تلاش کنید.")
        
    finally:
        # 4. پاک کردن فایل موقت برای خالی کردن فضای سرور
        if os.path.exists(temp_audio_file):
            os.remove(temp_audio_file)

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
            await message.reply(
                "❌ *لطفاً عبارت جستجو را وارد کنید.*\nمثال: `/search artist:Taylor Swift` یا `/search hello`")
            return

        query = parts[1].strip()
        if ":" in query:
            type_, term = query.split(":", 1)
            type_ = type_.lower()
            if type_ not in ["artist", "album", "track"]:
                await message.reply(
                    "❌ *نوع جستجو نامعتبر است.*\nیکی از گزینه‌های `artist`, `album`, `track` را انتخاب کنید.")
                return
        else:
            type_ = "all"
            term = query

        entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "all": "همه"}

        status_msg = await message.reply(f"🔍 *در حال جستجوی {type_fa_map[type_]}: {term}...*")

        search_id = generate_search_hash(type_, term)
        cache_key = f"search:{search_id}"

        results = await get_cached(cache_key)
        if not results:
            if type_ == "all":
                results = await search_itunes(term, entity=None, limit=50)
            else:
                results = await search_itunes(term, entity_map[type_], limit=50)
            if results and results.get("resultCount", 0) > 0:
                await set_cached(cache_key, "search", {"type": type_, "term": term, "data": results})

        if not results or results.get("resultCount", 0) == 0:
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
            status_msg = await bot.send_message(chat_id, "⏳ *در حال آماده‌سازی برای دانلود...*")
            track_data = await get_track(track_id)
            if track_data and track_data.get("results"):
                track = track_data["results"][0]
                t_name = track.get("trackName", "")
                a_name = track.get("artistName", "")
                asyncio.create_task(download_and_send_track(chat_id, t_name, a_name, status_msg))
            else:
                await status_msg.edit("❌ خطا در دریافت اطلاعات آهنگ.")

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

    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")


# ---------- Show entity details ----------
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

    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}"),
               row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 1)

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

    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:album:{album_id}"),
               row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 1)

    await status_msg.delete()

    artwork_url = get_high_res_artwork(album.get("artworkUrl100"))
    if artwork_url and not message_to_edit:
        try:
            await bot.send_photo(chat_id, photo=artwork_url, caption=text, components=markup)
            return
        except Exception as e:
            logger.error(f"Could not send album cover photo: {e}")

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

    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    sent_photo = False
    if artwork_url:
        try:
            if message_to_edit:
                pass
            else:
                await bot.send_photo(chat_id, photo=artwork_url, caption=text, components=markup)
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

    preview_url = track.get("previewUrl")
    if preview_url:
        try:
            await bot.send_audio(chat_id, audio=preview_url, caption="🎧 پیش‌نمایش صوتی ۳۰ ثانیه‌ای")
        except Exception as e:
            logger.error(f"Failed to send audio preview: {e}")


if __name__ == "__main__":
    logger.info("🎵 iTunes Music Bot Starting...")
    bot.run()
