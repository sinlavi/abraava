"""
bale_music_bot.py
Abraava Music Bot with advanced 8‑method YouTube Music downloader, metadata tagging, and caching.
Now featuring relational database for offline search & fallback.
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
from bale import Bot, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile, APIError
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, error

# Import the 8‑method downloader
from youtube_downloader import download_audio

# ---------- Configuration ----------
# PROXY_URL = "http://127.0.0.1:8085"        # change if needed
# VERIFY_SSL = False

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
OFFLINE_MODE = os.environ.get("OFFLINE_MODE", "false").lower() in ("true", "1", "yes")
if OFFLINE_MODE:
    logger.warning("🔴 Bot running in OFFLINE MODE – no external API calls will be made.")


# ---------- Async SQLite Database (relational) ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Preserve old cache table if needed (for search result caching)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                last_updated INTEGER NOT NULL
            )
        """)
        # New relational tables
        await db.execute("""
            CREATE TABLE IF NOT EXISTS artist (
                artistId INTEGER PRIMARY KEY,
                artistName TEXT,
                primaryGenreName TEXT,
                artistLinkUrl TEXT,
                artworkUrl100 TEXT,
                data TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS album (
                collectionId INTEGER PRIMARY KEY,
                artistId INTEGER,
                collectionName TEXT,
                releaseDate TEXT,
                primaryGenreName TEXT,
                artworkUrl100 TEXT,
                collectionViewUrl TEXT,
                data TEXT,
                FOREIGN KEY (artistId) REFERENCES artist(artistId)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS track (
                trackId INTEGER PRIMARY KEY,
                artistId INTEGER,
                collectionId INTEGER,
                trackName TEXT,
                trackTimeMillis INTEGER,
                primaryGenreName TEXT,
                releaseDate TEXT,
                trackViewUrl TEXT,
                previewUrl TEXT,
                artworkUrl100 TEXT,
                data TEXT,
                FOREIGN KEY (artistId) REFERENCES artist(artistId),
                FOREIGN KEY (collectionId) REFERENCES album(collectionId)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audio_cache (
                track_id INTEGER PRIMARY KEY,
                channel_message_id INTEGER NOT NULL
            )
        """)
        await db.commit()
    logger.info("Database initialized successfully (relational tables ready).")


# ---------- Relational DB store/retrieve helpers ----------
async def store_artist(item: dict):
    """Insert or replace an artist from iTunes API item into the artist table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO artist (artistId, artistName, primaryGenreName, artistLinkUrl, artworkUrl100, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item.get("artistId"),
            item.get("artistName", ""),
            item.get("primaryGenreName", ""),
            item.get("artistLinkUrl", ""),
            item.get("artworkUrl100", ""),
            json.dumps(item)
        ))
        await db.commit()


async def store_album(item: dict):
    """Insert or replace an album from iTunes API item into the album table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO album (collectionId, artistId, collectionName, releaseDate, 
                                          primaryGenreName, artworkUrl100, collectionViewUrl, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("collectionId"),
            item.get("artistId"),
            item.get("collectionName", ""),
            item.get("releaseDate", ""),
            item.get("primaryGenreName", ""),
            item.get("artworkUrl100", ""),
            item.get("collectionViewUrl", ""),
            json.dumps(item)
        ))
        await db.commit()


async def store_track(item: dict):
    """Insert or replace a track from iTunes API item into the track table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO track (trackId, artistId, collectionId, trackName, trackTimeMillis,
                                          primaryGenreName, releaseDate, trackViewUrl, previewUrl, artworkUrl100, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("trackId"),
            item.get("artistId"),
            item.get("collectionId"),
            item.get("trackName", ""),
            item.get("trackTimeMillis", 0),
            item.get("primaryGenreName", ""),
            item.get("releaseDate", ""),
            item.get("trackViewUrl", ""),
            item.get("previewUrl", ""),
            item.get("artworkUrl100", ""),
            json.dumps(item)
        ))
        await db.commit()


async def get_artist_db(artist_id: int) -> Optional[Dict[str, Any]]:
    """Fetch artist from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM artist WHERE artistId = ?", (artist_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                artist_data = json.loads(row[0])
                return {"resultCount": 1, "results": [artist_data]}
    return None


async def get_album_db(collection_id: int) -> Optional[Dict[str, Any]]:
    """Fetch album from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM album WHERE collectionId = ?", (collection_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                album_data = json.loads(row[0])
                return {"resultCount": 1, "results": [album_data]}
    return None


async def get_track_db(track_id: int) -> Optional[Dict[str, Any]]:
    """Fetch track from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM track WHERE trackId = ?", (track_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                track_data = json.loads(row[0])
                return {"resultCount": 1, "results": [track_data]}
    return None


# ---------- Old cache helpers (kept for search result sets) ----------
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
    if OFFLINE_MODE:
        logger.info(f"Offline mode: skipping iTunes API call to {endpoint}")
        return None
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
                # If rate limited (429) or other error, could fallback to local DB
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


# ---------- Local search (offline/fallback) ----------
async def local_search(term: str, entity: str = "all") -> Optional[Dict[str, Any]]:
    """Search the local relational database for the given term."""
    results = []
    pattern = f"%{term}%"

    if entity in ("artist", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT artistId, artistName, primaryGenreName, artworkUrl100, artistLinkUrl FROM artist WHERE artistName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "artist",
                        "artistId": row[0],
                        "artistName": row[1],
                        "primaryGenreName": row[2],
                        "artworkUrl100": row[3],
                        "artistLinkUrl": row[4]
                    })

    if entity in ("album", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT collectionId, artistId, collectionName, artworkUrl100 FROM album WHERE collectionName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "collection",
                        "collectionId": row[0],
                        "artistId": row[1],
                        "collectionName": row[2],
                        "artworkUrl100": row[3]
                    })

    if entity in ("track", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT trackId, artistId, collectionId, trackName, artworkUrl100 FROM track WHERE trackName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "track",
                        "trackId": row[0],
                        "artistId": row[1],
                        "collectionId": row[2],
                        "trackName": row[3],
                        "artworkUrl100": row[4]
                    })

    # Trim to overall limit 50 if entity is "all"
    if entity == "all":
        results = results[:50]
    return {"resultCount": len(results), "results": results}


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
                # Store album in relational DB
                await store_album(item)
                # Also crawl the tracks of this album to fully populate the cache
                await crawl_album_tracks(album_id, status_msg)
        await set_cached(cache_id, "artist_albums", {"albums": albums})


async def get_artist(artist_id: int, status_msg: Message = None) -> Optional[Dict[str, Any]]:
    # Try local DB first
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
        # Store in relational table
        for item in data["results"]:
            if item.get("wrapperType") == "artist":
                await store_artist(item)
        await crawl_artist_albums(artist_id, status_msg)
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
                # Store track in relational DB
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
        # Store album in relational DB
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
    """Search YouTube Music and return best video ID."""
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
async def send_audio_with_retry(bot: Bot, chat_id: int, audio_path, file_name: str, caption: str, max_retries=1):
    """Send audio with retry on gateway timeout (504)."""
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.warning('.'+str(audio_path))
            audio_file = InputFile('.' + str(audio_path), file_name=file_name)
            return await bot.send_audio(chat_id, audio=audio_file, caption=caption)
        except APIError as e:
            if "504" in str(e) or "Gateway Time-out" in str(e):
                logger.warning(f"send_audio 504, retry {attempt}/{max_retries}")
                last_exception = e
                await asyncio.sleep(attempt * 2)
            else:
                raise
        except Exception as e:
            last_exception = e
            break
    raise last_exception


async def send_cached_or_download(bot: Bot, chat_id: int, track_id: int):
    status_msg = await bot.send_message(chat_id, f"⏳ *در حال آماده‌سازی دانلود از {BOT_NAME}...*{FOOTER}")

    # Check if already cached in DB Channel
    channel_msg_id = await get_audio_cache(track_id)
    if channel_msg_id and DB_CHANNEL_ID:
        try:
            await bot.forward_message(chat_id, from_chat_id=DB_CHANNEL_ID, message_id=channel_msg_id)
            await status_msg.edit(f"✅ آهنگ با موفقیت از دیتابیس {BOT_NAME} دریافت شد.{FOOTER}")
            return
        except Exception as e:
            logger.error(f"Forward failed: {e}, will re-download")

    # In offline mode we cannot download – error out
    if OFFLINE_MODE:
        await status_msg.edit(f"❌ آهنگ در دیتابیس محلی یافت نشد و بات در حالت آفلاین است.{FOOTER}")
        return
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
                db_msg = await send_audio_with_retry(
                    bot, int(DB_CHANNEL_ID), mp3_path, f"{t_name}.mp3", caption
                )

                if db_msg and db_msg.message_id:
                    # Cache successful, save ID
                    await set_audio_cache(track_id, int(db_msg.message_id))
                    # Forward to User
                    await bot.forward_message(chat_id, from_chat_id=DB_CHANNEL_ID, message_id=db_msg.message_id)
                    await status_msg.edit(f"✅ دانلود و پردازش با موفقیت انجام شد.{FOOTER}")
            except Exception as e:
                logger.error(f"Error caching to DB_CHANNEL: {e}")
                # Retry sending directly to user with the same bytes
                await send_audio_with_retry(bot, chat_id, mp3_path, f"{t_name}.mp3", caption)
                await status_msg.edit(f"✅ آهنگ مستقیما ارسال شد (خطا در ذخیره دیتابیس).{FOOTER}")
        else:
            await send_audio_with_retry(bot, chat_id, mp3_path, f"{t_name}.mp3", caption)
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
                    await bot.send_audio(chat_id, audio=voice_input,
                                         caption=f"🎧 پیش‌نمایش صوتی آهنگ {track.get('trackName')}{FOOTER}")
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


async def edit_or_send(bot: Bot, chat_id: int, message_to_edit: Optional[Message], text: str,
                       markup: InlineKeyboardMarkup, photo_bytes: Optional[bytes] = None):
    """
    Safely edit a message (caption or text) or send a new one if editing fails.
    If photo_bytes is given, send as photo; otherwise send as text.
    """
    if message_to_edit:
        try:
            # If the existing message is a photo, edit caption
            if message_to_edit.photo:
                if photo_bytes:
                    # Can't edit photo media, just edit caption
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_to_edit.message_id,
                        caption=text,
                        reply_markup=markup
                    )
                else:
                    # Was a photo but now we want to send text-only? Delete and send new
                    await message_to_edit.delete()
                    await bot.send_message(chat_id, text, components=markup)
            else:
                # Text message
                await message_to_edit.edit(text, components=markup)
            return
        except Exception as e:
            logger.warning(f"Edit failed: {e}, sending new message")

    # Send new
    if photo_bytes:
        await bot.send_photo(chat_id, photo=InputFile(photo_bytes, file_name="cover.jpg"), caption=text,
                             components=markup)
    else:
        await bot.send_message(chat_id, text, components=markup)


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
            return
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
            await message.reply(
                f"❌ *لطفاً عبارت جستجو را وارد کنید.*\nمثال: `/search artist:Taylor Swift` یا `/search hello`{FOOTER}")
            return
        query = parts[1].strip()
        if ":" in query:
            type_, term = query.split(":", 1)
            type_ = type_.lower()
            if type_ not in ["artist", "album", "track"]:
                await message.reply(
                    f"❌ *نوع جستجو نامعتبر است.*\nیکی از گزینه‌های `artist`, `album`, `track` را انتخاب کنید.{FOOTER}")
                return
        else:
            type_ = "all"
            term = query

        entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ", "all": "همه"}
        status_msg = await message.reply(f"🔍 *در حال جستجوی {type_fa_map[type_]}: {term}...*{FOOTER}")

        search_id = generate_search_hash(type_, term)
        cache_key = f"search:{search_id}"

        # Attempt online search first, fallback to local DB on failure or offline
        results = None
        if not OFFLINE_MODE:
            if type_ == "all":
                results = await search_itunes(term, entity=None, limit=50)
            else:
                results = await search_itunes(term, entity_map[type_], limit=50)

        # If online failed or offline, try local DB
        if results is None:
            results = await local_search(term, type_)

        if results and results.get("resultCount", 0) > 0:
            await set_cached(cache_key, "search", {"type": type_, "term": term, "data": results})
            # Store results in relational DB for future offline use (only if online result)
            if not OFFLINE_MODE:
                for item in results["results"]:
                    # store by type
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
        await send_search_page(message.chat.id, search_id, 1, message_to_edit=None, original_term=term)


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

    markup = InlineKeyboardMarkup()
    if type_ == "all":
        header = f"📋 *نتایج جستجوی ترکیبی برای: {term}*\nتعداد کل: {total_items} مورد"
    else:
        type_fa_map = {"artist": "هنرمند", "album": "آلبوم", "track": "آهنگ"}
        header = f"📋 *نتایج جستجو برای {type_fa_map[type_]}: {term}*\nتعداد کل: {total_items} مورد"

    # Add result buttons
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

    # Pagination row
    if total_pages > 1:
        pagination_row = create_pagination_row(f"page:search:{search_id}", page, total_pages)
        for btn in pagination_row:
            markup.add(btn, row=len(page_items) + 1)
        current_row = len(page_items) + 2
    else:
        current_row = len(page_items) + 1

    # Refinement buttons (always show, using cached term)
    refine_term = term  # use the term from cache
    if refine_term:
        markup.add(InlineKeyboardButton(text="🔍 جستجو در آلبوم‌ها", callback_data=f"refine:album:{refine_term}"),
                   row=current_row)
        markup.add(InlineKeyboardButton(text="🔍 جستجو در هنرمندان", callback_data=f"refine:artist:{refine_term}"),
                   row=current_row + 1)
        markup.add(InlineKeyboardButton(text="🔍 جستجو در آهنگ‌ها", callback_data=f"refine:track:{refine_term}"),
                   row=current_row + 2)
        new_search_row = current_row + 3
    else:
        new_search_row = current_row

    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=new_search_row)

    text = header + FOOTER
    await edit_or_send(bot, chat_id, message_to_edit, text, markup)


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
        elif data.startswith("refine:"):
            entity = parts[1]  # album, artist, track
            term = parts[2]
            entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
            if entity not in entity_map:
                await bot.send_message(chat_id, "نوع فیلتر نامعتبر است.")
                return
            status_msg = await bot.send_message(chat_id, f"🔍 *در حال جستجوی {entity} برای: {term}...*{FOOTER}")
            # Online search, fallback to local
            results = None
            if not OFFLINE_MODE:
                results = await search_itunes(term, entity=entity_map[entity], limit=50)
            if results is None:
                results = await local_search(term, entity)
            if results and results.get("resultCount", 0) > 0:
                search_id = generate_search_hash(entity, term)
                await set_cached(f"search:{search_id}", "search", {"type": entity, "term": term, "data": results})
                # Store items if online
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
            await show_artist(chat_id, artist_id, page, callback.message)
        elif data.startswith("album:"):
            album_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 1
            # Check if album has exactly one track -> redirect to track
            cached_album_tracks = await get_cached(f"album_tracks:{album_id}")
            if not cached_album_tracks:
                # Album tracks not yet crawled, fetch first
                await crawl_album_tracks(album_id)
                cached_album_tracks = await get_cached(f"album_tracks:{album_id}")
            if cached_album_tracks and "tracks" in cached_album_tracks:
                track_ids = cached_album_tracks["tracks"]
                if len(track_ids) == 1:
                    # Single track album - show track directly
                    await show_track(chat_id, track_ids[0], callback.message)
                    return
            # Otherwise show album page
            await show_album(chat_id, album_id, page, callback.message)
        elif data.startswith("track:"):
            track_id = int(parts[1])
            await show_track(chat_id, track_id, callback.message)
        elif data.startswith("download:"):
            track_id = int(parts[1])
            await send_cached_or_download(bot, chat_id, track_id)
        elif data.startswith("preview:"):
            track_id = int(parts[1])
            await send_voice_preview(chat_id, track_id)
        elif data.startswith("recrawl:"):
            type_ = parts[1]
            id_ = int(parts[2])
            # Remove from local relational tables as well
            if type_ == "artist":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM artist WHERE artistId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"artist:{id_}")
                await delete_cached(f"artist_albums:{id_}")
                await show_artist(chat_id, id_, 1, callback.message)
            elif type_ == "album":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM album WHERE collectionId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"album:{id_}")
                await delete_cached(f"album_tracks:{id_}")
                await show_album(chat_id, id_, 1, callback.message)
            elif type_ == "track":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM track WHERE trackId = ?", (id_,))
                    await db.commit()
                await delete_cached(f"track:{id_}")
                await show_track(chat_id, id_, callback.message)
    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")


# ---------- Show functions (improved for photo caption editing) ----------
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
            album_data = await get_album_db(album_id)  # prefer local DB
            if album_data and album_data.get("results"):
                albums.append(album_data["results"][0])
            else:
                # fallback to old cache if not in DB
                album_data_cache = await get_cached(f"album:{album_id}")
                if album_data_cache and album_data_cache.get("results"):
                    albums.append(album_data_cache["results"][0])

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
        bottom_row = len(page_items) + 2 if total_pages > 1 else len(page_items) + 1
    else:
        bottom_row = 1

    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}"),
               row=bottom_row)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row + 1)

    text += FOOTER
    await status_msg.delete()

    artwork_url = get_high_res_artwork(artist.get("artworkUrl100"))
    photo_bytes = None
    if artwork_url:
        async with aiohttp.ClientSession() as session:
            async with session.get(artwork_url) as resp:
                if resp.status == 200:
                    photo_bytes = await resp.read()

    await edit_or_send(bot, chat_id, message_to_edit, text, markup, photo_bytes)


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
        bottom_row = len(page_items) + 2 if total_pages > 1 else len(page_items) + 1
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
    photo_bytes = None
    if artwork_url:
        async with aiohttp.ClientSession() as session:
            async with session.get(artwork_url) as resp:
                if resp.status == 200:
                    photo_bytes = await resp.read()

    await edit_or_send(bot, chat_id, message_to_edit, text, markup, photo_bytes)


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

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="⬇️ دانلود کامل آهنگ (320 kbps)", callback_data=f"download:{track_id}"), row=1)

    row = 2
    if track.get("previewUrl"):
        markup.add(InlineKeyboardButton(text="🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"), row=row)
        row += 1

    if track.get('collectionId'):
        markup.add(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"album:{track['collectionId']}:1"),
                   row=row)
    if track.get('artistId'):
        markup.add(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"), row=row)

    markup.add(InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}"), row=row + 1)
    markup.add(InlineKeyboardButton(text="🔍 جستجوی جدید", callback_data="new_search"), row=row + 2)

    text += FOOTER
    await status_msg.delete()

    artwork_url = get_high_res_artwork(track.get("artworkUrl100"))
    photo_bytes = None
    if artwork_url:
        async with aiohttp.ClientSession() as session:
            async with session.get(artwork_url) as resp:
                if resp.status == 200:
                    photo_bytes = await resp.read()

    await edit_or_send(bot, chat_id, message_to_edit, text, markup, photo_bytes)


if __name__ == "__main__":
    logger.info(f"🎵 {BOT_NAME} Music Bot Starting (with relational DB & offline search)...")
    bot.run()
