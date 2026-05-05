import asyncio
import os
import re
import sqlite3
import logging
from pathlib import Path
import yt_dlp
from balethon import Client
from balethon.conditions import command, text
from balethon.objects import InlineKeyboard

# ===================== تنظیمات لاگر =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ===================== تنظیمات =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BALE_BOT_TOKEN")
CACHE_CHANNEL_ID = int(os.getenv("CACHE_CHANNEL_ID", "-1000000000000"))

TEMP_DIR = Path("temp_soundcloud")
TEMP_DIR.mkdir(exist_ok=True)
DB_PATH = "cache.db"

bot = Client(BOT_TOKEN)
BOT_USERNAME = "" 

# ===================== دیتابیس =====================
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        fields = [
            "uuid TEXT PRIMARY KEY", "title TEXT", "uploader TEXT", "genre TEXT",
            "upload_date TEXT", "webpage_url TEXT", "thumbnail TEXT", "cache_msg_id TEXT",
            "duration TEXT"
        ]
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(f"CREATE TABLE IF NOT EXISTS tracks ({', '.join(fields)})")
            c.execute("PRAGMA table_info(tracks)")
            cols = [r[1] for r in c.fetchall()]
            needed_cols = [f.split()[0] for f in fields]
            if set(cols) != set(needed_cols):
                c.execute("DROP TABLE IF EXISTS tracks")
                c.execute(f"CREATE TABLE tracks ({', '.join(fields)})")
            conn.commit()

    def run_query(self, query, params=(), fetch=False, fetchone=False):
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
            logger.error(f"Database error: {e} | Query: {query}")
            return {} if fetchone else []

db = DatabaseManager(DB_PATH)


def build_caption(track, bot_user):
    return (
        f"🎧 *{track.get('title','نامشخص')}*\n"
        f"🎤 هنرمند: *{track.get('uploader','نامشخص')}*\n"
        f"📅 سال: {track.get('upload_date','نامشخص')}\n"
        f"🎸 ژانر: {track.get('genre','نامشخص')}\n"
        f"⏱ مدت: {track.get('duration','نامشخص')}\n"
        f"🔗 [لینک اصلی]({track.get('webpage_url','نامشخص')})\n\n"
        f"🤖 @{bot_user}"
    )

def format_duration(seconds):
    if not seconds: return "نامشخص"
    try:
        s = int(float(seconds))
        return f"{s // 60}:{s % 60:02d}"
    except:
        return str(seconds)

# =================== توابع ساندکلاود ==================
def get_soundcloud_info(url):
    ydl_opts = {"quiet": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def download_soundcloud_track(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = str(TEMP_DIR / f"{info['id']}.mp3") 
        return filepath, info

async def search_soundcloud(query, max_results=10):
    results = []
    ydl_opts = {"quiet": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
        for e in info.get("entries", []):
            results.append({
                "id": e.get("id"),
                "title": e.get("title", "بدون نام"),
                "uploader": e.get("uploader", "نامشخص"),
                "webpage_url": e.get("webpage_url", "").split('?')[0],
                "thumbnail": e.get("thumbnail", ""),
                "duration": e.get("duration", 0)
            })
    return results

def get_search_text(results):
    text = ""
    for item in results:
        text += f"👤 {item['uploader']}\n"
        text += f"🎵 {item['title']}\n"
        text += f"⏱️ {format_duration(item.get('duration'))}\n"
        text += f"[📥 دریافت](send:{item['webpage_url']})\n\n"
    return text

# =================== هندلر start ==================
@bot.on_message(command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await client.get_me()).username
    logger.info(f"User {message.author.id} started the bot.")
    await message.reply("🎶 به ربات دانلودر ساندکلاود خوش آمدید!\nلینک بفرستید یا متن جستجو کنید.")

# =================== هندلر متنی ==================
@bot.on_message(text)
async def handle_text(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME: 
        BOT_USERNAME = (await client.get_me()).username
    
    content = message.text.strip()
    
    if message.chat.type != "private":
        mention = f"@{BOT_USERNAME}"
        if mention not in content: return
        content = content.replace(mention, "").strip()
        if not content: return

    if "soundcloud.com" in content:
        url_match = re.search(r"(https?://[^\s]+)", content)
        if not url_match: return await message.reply("❌ لینک نامعتبر!")
        
        # پاکسازی لینک از پارامترهای اضافه برای جستجوی دقیق‌تر در دیتابیس
        url = url_match.group(1).split('?')[0]
        
        logger.info(f"Processing URL: {url} by user {message.author.id}")
        msg = await message.reply("⏳ در حال بررسی...")
        
        # بررسی وجود لینک در دیتابیس
        cached_track = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        
        if cached_track:
            logger.info("Found URL in DB cache.")
            meta = cached_track
            track_id = meta["uuid"].replace("sc_", "")
            await msg.delete()
        else:
            logger.info("URL not in DB, fetching from SoundCloud...")
            loop = asyncio.get_event_loop()
            try:
                info = await loop.run_in_executor(None, get_soundcloud_info, url)
            except Exception as e:
                logger.error(f"Error extracting info for {url}: {e}")
                return await msg.edit_text(f"❌ خطا در دریافت اطلاعات: {e}")

            track_id = info.get('id', 'unknown')
            clean_url = info.get("webpage_url", url).split('?')[0]
            meta = {
                "uuid": f"sc_{track_id}",
                "title": info.get("title", ""),
                "uploader": info.get("uploader", ""),
                "genre": info.get("genre", ""),
                "upload_date": str(info.get("upload_date", ""))[:4],
                "webpage_url": clean_url,
                "thumbnail": info.get("thumbnail", ""),
                "duration": format_duration(info.get("duration", 0)),
            }
            
            placeholders = ','.join(['?'] * len(meta))
            db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({placeholders})", tuple(meta.values()))
            await msg.delete()
            
        caption = build_caption(meta, BOT_USERNAME)
        buttons = [[("⬇️ دریافت فایل صوتی", f"getaudio:{track_id}")]]
        
        if meta.get("thumbnail"):
            await client.send_photo(message.chat.id, meta["thumbnail"], caption=caption, reply_markup=InlineKeyboard(*buttons))
        else:
            await client.send_message(message.chat.id, caption, reply_markup=InlineKeyboard(*buttons))
        return

    logger.info(f"Searching SoundCloud for: {content} by user {message.author.id}")
    msg = await message.reply("🔍 در حال جستجو...")
    try:
        # فقط 10 نتیجه اول را دریافت میکنیم
        results = await search_soundcloud(content, 10)
    except Exception as e:
        logger.error(f"Search error for query '{content}': {e}")
        await msg.delete()
        return await message.reply("❌ خطا در جستجو.")

    if not results:
        await msg.delete()
        return await message.reply("😔 موردی یافت نشد.")

    text_res = get_search_text(results)
    
    await msg.delete()
    await message.reply(text_res)


# =================== هندلر دکمه‌های شیشه‌ای ==================
@bot.on_callback_query()
async def handle_callback(client, callback_query):
    global BOT_USERNAME
    if not BOT_USERNAME: 
        BOT_USERNAME = (await client.get_me()).username
    
    data = callback_query.data

    if data.startswith("getaudio:"):       
        parts = data.split(":")
        if len(parts) < 2: return
        track_id = parts[1]
        
        logger.info(f"User {callback_query.author.id} requested audio for track {track_id}")
        await callback_query.answer("⏳ در حال پردازش فایل، لطفا صبور باشید...")
        
        row = db.run_query("SELECT * FROM tracks WHERE uuid=?", (f"sc_{track_id}",), fetchone=True)
        if not row:
            logger.warning(f"Track {track_id} not found in DB.")
            return await callback_query.message.reply("❌ اطلاعات این آهنگ منقضی شده است. لطفا دوباره لینک را بفرستید.")

        caption = build_caption(row, BOT_USERNAME)
        msg_to_delete = callback_query.message
        url = row.get("webpage_url")

        # در صورت وجود در کانال کش، مستقیماً فوروارد می‌شود
        if row.get("cache_msg_id"):
            try:
                logger.info(f"Forwarding cached message {row['cache_msg_id']} to user.")
                await client.forward_message(
                    chat_id=callback_query.message.chat.id,
                    from_chat_id=CACHE_CHANNEL_ID,
                    message_id=int(row["cache_msg_id"])
                )
                await msg_to_delete.delete()
                return
            except Exception as e:
                logger.error(f"Failed to forward cached message: {e}")

        logger.info(f"Downloading track: {url}")
        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return await callback_query.message.reply(f"❌ خطا در دانلود: {e}")

        try:
            logger.info(f"Uploading file {filepath} to cache channel {CACHE_CHANNEL_ID}")
            with open(filepath, "rb") as f:
                sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f, caption=caption)
            
            msg_id = sent_msg.id
            if msg_id:
                # ذخیره آیدی پیام کش شده در دیتابیس
                row["cache_msg_id"] = str(msg_id)
                placeholders = ','.join(['?'] * len(row))
                db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(row.keys())}) VALUES ({placeholders})", tuple(row.values()))
            
            logger.info(f"Forwarding newly uploaded message {msg_id} to user.")
            await client.forward_message(
                chat_id=callback_query.message.chat.id,
                from_chat_id=CACHE_CHANNEL_ID,
                message_id=msg_id
            )
            await msg_to_delete.delete()
            
        except Exception as e:
            logger.error(f"Upload/Forward error: {e}")
            await callback_query.message.reply(f"❌ خطا در آپلود یا ارسال فایل: {e}")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Deleted temp file: {filepath}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run()
