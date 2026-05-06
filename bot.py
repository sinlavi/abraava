import asyncio
import os
import re
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import yt_dlp
from balethon import Client
from balethon.conditions import command, text, private, chat  # ← REMOVED callback_query
from balethon.objects import InlineKeyboard, InlineKeyboardButton, Message

# ------------------- Logging -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MusicBot")

# ------------------- Configuration -------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BALE_BOT_TOKEN")
CACHE_CHANNEL_ID = int(os.getenv("CACHE_CHANNEL_ID", "-1000000000000"))
BROADCAST_CHANNEL_ID = int(os.getenv("BROADCAST_CHANNEL_ID", "0"))  # 0 = disabled

TEMP_DIR = Path("temp_music")
TEMP_DIR.mkdir(exist_ok=True)
DB_PATH = "music_cache.db"

bot = Client(BOT_TOKEN)
BOT_USERNAME: str = ""

# ------------------- Database -------------------
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            # Drop old table if it doesn't have the 'source' column
            c.execute("PRAGMA table_info(tracks)")
            cols = [row[1] for row in c.fetchall()] if c.fetchone() is not None else []
            if "source" not in cols:
                c.execute("DROP TABLE IF EXISTS tracks")
            c.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    uuid TEXT PRIMARY KEY,
                    title TEXT,
                    uploader TEXT,
                    genre TEXT,
                    upload_date TEXT,
                    webpage_url TEXT,
                    thumbnail TEXT,
                    cache_msg_id TEXT,
                    duration TEXT,
                    source TEXT NOT NULL DEFAULT 'soundcloud'
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY
                )
            """)
            conn.commit()

    def execute(self, query: str, params=(), fetch=False, fetchone=False):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute(query, params)
                if fetchone:
                    row = c.fetchone()
                    return dict(row) if row else {}
                if fetch:
                    return [dict(r) for r in c.fetchall()]
                conn.commit()
        except Exception as e:
            logger.error(f"DB error: {e} | query: {query}")
            return {} if fetchone else []

    def save_track(self, track: Dict[str, Any]):
        placeholders = ", ".join(["?"] * len(track))
        columns = ", ".join(track.keys())
        self.execute(
            f"INSERT OR REPLACE INTO tracks ({columns}) VALUES ({placeholders})",
            tuple(track.values()),
        )

    def get_track(self, uuid: str) -> Dict[str, Any]:
        return self.execute("SELECT * FROM tracks WHERE uuid = ?", (uuid,), fetchone=True)

    def add_user(self, chat_id: int):
        self.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))

    def get_all_users(self) -> List[Dict[str, Any]]:
        return self.execute("SELECT chat_id FROM users", fetch=True)


db = Database(DB_PATH)

# ------------------- Helpers -------------------
def format_duration(seconds) -> str:
    if not seconds:
        return "نامشخص"
    try:
        s = int(float(seconds))
        return f"{s // 60}:{s % 60:02d}"
    except (ValueError, TypeError):
        return str(seconds)

def build_caption(track: Dict[str, Any], bot_username: str) -> str:
    lines = [
        f"🎧 *{track.get('title', 'نامشخص')}*",
        f"🎤 هنرمند: *{track.get('uploader', 'نامشخص')}*",
    ]
    if track.get("source") == "soundcloud" and track.get("genre"):
        lines.append(f"🎸 ژانر: {track['genre']}")
    lines += [
        f"📅 سال: {track.get('upload_date', 'نامشخص')}",
        f"⏱ مدت: {track.get('duration', 'نامشخص')}",
        f"🔗 [لینک اصلی]({track.get('webpage_url', 'نامشخص')})",
        f"🤖 @{bot_username}",
    ]
    return "\n".join(lines)

# ------------------- yt-dlp wrapper -------------------
def _extract_info(url: str, download: bool = False, extra_opts: dict = None) -> dict:
    """Synchronous extraction, to be run in executor."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": not download,
    }
    if extra_opts:
        opts.update(extra_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)

async def extract_audio(url: str) -> (Path, dict):
    """Download best audio and convert to mp3. Returns (file_path, info_dict)."""
    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _extract_info, url, True, opts)
    file_path = TEMP_DIR / f"{info['id']}.mp3"
    return file_path, info

async def fetch_track_info(url: str, source: str) -> Dict[str, Any]:
    """Extract metadata for DB from a track URL."""
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _extract_info, url, False)
    clean_url = info.get("webpage_url", url).split("?")[0]
    track_id = info.get("id", "unknown")
    uuid = f"{source}_{track_id}"
    duration = format_duration(info.get("duration", 0))
    genre = info.get("genre", "") if source == "soundcloud" else ""
    upload_date = str(info.get("upload_date", ""))[:4] if info.get("upload_date") else "نامشخص"
    return {
        "uuid": uuid,
        "title": info.get("title", "نامشخص"),
        "uploader": info.get("uploader", "نامشخص"),
        "genre": genre,
        "upload_date": upload_date,
        "webpage_url": clean_url,
        "thumbnail": info.get("thumbnail", ""),
        "duration": duration,
        "source": source,
        "cache_msg_id": None,
    }

async def search_soundcloud(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _extract_info, f"scsearch{limit}:{query}", False)
    results = []
    for entry in data.get("entries", []):
        results.append({
            "id": entry.get("id"),
            "title": entry.get("title", "بدون نام"),
            "uploader": entry.get("uploader", "نامشخص"),
            "webpage_url": entry.get("webpage_url", "").split("?")[0],
            "thumbnail": entry.get("thumbnail", ""),
            "duration": entry.get("duration", 0),
            "source": "soundcloud",
        })
    return results

async def search_youtube_music(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _extract_info, f"ytmusic{limit}:{query}", False)
    results = []
    for entry in data.get("entries", []):
        results.append({
            "id": entry.get("id"),
            "title": entry.get("title", "بدون نام"),
            "uploader": entry.get("uploader", "نامشخص"),
            "webpage_url": f"https://music.youtube.com/watch?v={entry.get('id')}",
            "thumbnail": entry.get("thumbnail", ""),
            "duration": entry.get("duration", 0),
            "source": "youtube",
        })
    return results

# ------------------- Download locks -------------------
_download_locks: Dict[str, asyncio.Lock] = {}

async def get_or_create_lock(key: str) -> asyncio.Lock:
    if key not in _download_locks:
        _download_locks[key] = asyncio.Lock()
    return _download_locks[key]

# ------------------- Handlers -------------------
@bot.on_message(command("start"))
async def start_handler(_, message: Message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await bot.get_me()).username
    if message.chat.type == "private":
        db.add_user(message.chat.id)
    await message.reply(
        "🎶 به ربات موزیک خوش آمدید!\n"
        "• لینک SoundCloud یا YouTube Music بفرستید.\n"
        "• برای جستجو در SoundCloud یک متن ساده بفرستید.\n"
        "• برای جستجو در YouTube Music از دستور /ytmusic استفاده کنید.\n"
        "مثال: `/ytmusic relax`"
    )

@bot.on_message(command("ytmusic"))
async def ytmusic_search_handler(_, message: Message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await bot.get_me()).username
    if message.chat.type == "private":
        db.add_user(message.chat.id)

    query = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if not query:
        return await message.reply("❌ لطفاً متن جستجو را وارد کنید. مثال: `/ytmusic lofi`")

    logger.info(f"YouTube Music search: {query} by {message.author.id}")
    status = await message.reply("🔍 در حال جستجو در YouTube Music...")
    try:
        results = await search_youtube_music(query)
    except Exception as e:
        logger.error(f"YT music search error: {e}")
        await status.delete()
        return await message.reply("❌ خطا در جستجوی YouTube Music.")

    if not results:
        await status.delete()
        return await message.reply("😔 نتیجه‌ای یافت نشد.")

    text_res = "🎵 نتایج جستجو در YouTube Music:\n\n"
    for item in results:
        text_res += (
            f"👤 {item['uploader']}\n"
            f"🎵 {item['title']}\n"
            f"⏱️ {format_duration(item.get('duration'))}\n"
            f"[📥 دریافت](send:{item['webpage_url']})\n\n"
        )
    await status.delete()
    await message.reply(text_res)

@bot.on_message(text & ~command("start") & ~command("ytmusic"))
async def text_handler(_, message: Message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await bot.get_me()).username

    if message.chat.type == "private":
        db.add_user(message.chat.id)

    content = message.text.strip()
    # If not private, only respond when mentioned or link shared
    if message.chat.type != "private":
        mention = f"@{BOT_USERNAME}"
        if mention not in content.lower() and not any(domain in content.lower() for domain in ["soundcloud.com", "youtube.com", "youtu.be", "music.youtube.com"]):
            return
        content = content.replace(mention, "").strip()
        if not content:
            return

    # Extract URL
    url_match = re.search(r"(https?://[^\s]+)", content)
    if url_match:
        url = url_match.group(1).split("?")[0]
        # Determine source
        if "soundcloud.com" in url:
            source = "soundcloud"
        elif any(d in url for d in ["youtube.com", "youtu.be", "music.youtube.com"]):
            source = "youtube"
        else:
            # Treat as SoundCloud by default if link but not recognized? Maybe send error.
            return await message.reply("❌ لینک پشتیبانی نمی‌شود.")

        logger.info(f"Processing {source}: {url} by {message.author.id}")
        status = await message.reply("⏳ در حال دریافت اطلاعات...")

        # Check cache
        cached_track = db.execute(
            "SELECT * FROM tracks WHERE webpage_url = ? AND source = ?",
            (url, source),
            fetchone=True,
        )
        if cached_track:
            logger.info("Found in cache")
            await status.delete()
            meta = cached_track
        else:
            try:
                meta = await fetch_track_info(url, source)
                db.save_track(meta)
            except Exception as e:
                logger.error(f"Info extraction error: {e}")
                await status.edit_text(f"❌ خطا: {e}")
                return
            await status.delete()

        caption = build_caption(meta, BOT_USERNAME)
        track_id = meta["uuid"].split("_", 1)[1]
        buttons = InlineKeyboard(
            [InlineKeyboardButton("⬇️ دریافت فایل صوتی", callback_data=f"getaudio:{meta['source']}:{track_id}")]
        )
        if meta.get("thumbnail"):
            await message.reply_photo(meta["thumbnail"], caption=caption, reply_markup=buttons)
        else:
            await message.reply(caption, reply_markup=buttons)
        return

    # Plain text → SoundCloud search (original behaviour)
    query = content
    logger.info(f"SoundCloud search: {query} by {message.author.id}")
    status = await message.reply("🔍 در حال جستجو در SoundCloud...")
    try:
        results = await search_soundcloud(query)
    except Exception as e:
        logger.error(f"SoundCloud search error: {e}")
        await status.delete()
        return await message.reply("❌ خطا در جستجوی SoundCloud.")

    if not results:
        await status.delete()
        return await message.reply("😔 نتیجه‌ای یافت نشد.")

    text_res = "🎵 نتایج جستجو در SoundCloud:\n\n"
    for item in results:
        text_res += (
            f"👤 {item['uploader']}\n"
            f"🎵 {item['title']}\n"
            f"⏱️ {format_duration(item.get('duration'))}\n"
            f"[📥 دریافت](send:{item['webpage_url']})\n\n"
        )
    await status.delete()
    await message.reply(text_res)

@bot.on_callback_query()
async def callback_handler(_, cb):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await bot.get_me()).username

    data = cb.data
    if data == "ignore":
        return await cb.answer("در حال پردازش هستیم...")

    if data.startswith("getaudio:"):
        parts = data.split(":")
        if len(parts) < 3:
            return
        _, source, track_id = parts
        uuid = f"{source}_{track_id}"

        logger.info(f"Audio requested for {uuid} by {cb.author.id}")
        await cb.answer("⏳ در حال آماده‌سازی فایل...")

        # Update message to show downloading state
        downloading_keyboard = InlineKeyboard(
            [InlineKeyboardButton("⏳ در حال دریافت فایل...", callback_data="ignore")]
        )
        downloading_text = "⏳ *در حال دانلود و آماده‌سازی فایل...*"
        try:
            if cb.message.photo:
                await bot.edit_message_caption(
                    chat_id=cb.message.chat.id,
                    message_id=cb.message.id,
                    caption=downloading_text,
                    reply_markup=downloading_keyboard,
                )
            else:
                await bot.edit_message_text(
                    chat_id=cb.message.chat.id,
                    message_id=cb.message.id,
                    text=downloading_text,
                    reply_markup=downloading_keyboard,
                )
        except Exception as e:
            logger.warning(f"Could not update message UI: {e}")

        track = db.get_track(uuid)
        if not track:
            return await cb.message.reply("❌ اطلاعات این آهنگ منقضی شده است. لطفاً لینک را دوباره بفرستید.")

        # If cached message exists, forward it
        if track.get("cache_msg_id"):
            try:
                await bot.forward_message(
                    chat_id=cb.message.chat.id,
                    from_chat_id=CACHE_CHANNEL_ID,
                    message_id=int(track["cache_msg_id"]),
                )
                await cb.message.delete()
                return
            except Exception as e:
                logger.error(f"Forward cached failed: {e}")

        # Download
        lock = await get_or_create_lock(uuid)
        async with lock:
            url = track["webpage_url"]
            file_path = None
            try:
                file_path, info = await extract_audio(url)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                await cb.message.reply(f"❌ خطا در دانلود: {e}")
                return

            try:
                # Upload to cache channel
                with open(file_path, "rb") as f:
                    sent = await bot.send_audio(
                        CACHE_CHANNEL_ID,
                        f,
                        title=track["title"],
                        caption=build_caption(track, BOT_USERNAME),
                    )
                # Update DB with cache message id
                track["cache_msg_id"] = str(sent.id)
                db.save_track(track)

                # Forward to user
                await bot.forward_message(
                    chat_id=cb.message.chat.id,
                    from_chat_id=CACHE_CHANNEL_ID,
                    message_id=sent.id,
                )
                await cb.message.delete()
            except Exception as e:
                logger.error(f"Upload/forward error: {e}")
                await cb.message.reply(f"❌ خطا در ارسال فایل: {e}")
            finally:
                if file_path and file_path.exists():
                    file_path.unlink(missing_ok=True)

@bot.on_message(chat(BROADCAST_CHANNEL_ID))
async def broadcast_handler(_, message: Message):
    if BROADCAST_CHANNEL_ID == 0:
        return
    logger.info(f"New message in broadcast channel {BROADCAST_CHANNEL_ID}. Forwarding to users...")
    users = db.get_all_users()
    success = 0
    for u in users:
        try:
            await bot.forward_message(
                chat_id=u["chat_id"],
                from_chat_id=message.chat.id,
                message_id=message.id,
            )
            success += 1
            await asyncio.sleep(0.05)  # rate limit
        except Exception as e:
            logger.error(f"Failed to forward to {u['chat_id']}: {e}")
    logger.info(f"Broadcast done. Forwarded to {success} users.")

# ------------------- Entry Point -------------------
if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run()
