import asyncio
import os
import re
import sqlite3
import logging
from pathlib import Path
import yt_dlp
from balethon import Client
from balethon.conditions import command, text, private, chat
from balethon.objects import InlineKeyboard, InlineKeyboardButton

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
BROADCAST_CHANNEL_ID = 5524168471

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
            
            c.execute("PRAGMA table_info(tracks)")
            existing_cols = [r[1] for r in c.fetchall()]
            needed_cols = [f.split()[0] for f in fields]
            
            if existing_cols and set(existing_cols) != set(needed_cols):
                logger.warning("Database schema mismatch detected. Dropping all tables...")
                c.execute("DROP TABLE IF EXISTS tracks")
                c.execute("DROP TABLE IF EXISTS users")
            
            c.execute(f"CREATE TABLE IF NOT EXISTS tracks ({', '.join(fields)})")
            c.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)")
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

def track_user(chat_id):
    db.run_query("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))

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

def search_soundcloud_sync(query, max_results=10):
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

async def search_soundcloud(query, max_results=10):
    # برای جلوگیری از فریز شدن بات، جستجو به ThreadPool منتقل شد
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_soundcloud_sync, query, max_results)

def get_search_text(results):
    text = "🔍 *نتایج جستجو:*\n\n"
    for item in results:
        text += f"👤 {item['uploader']}\n"
        text += f"🎵 {item['title']}\n"
        text += f"⏱️ {format_duration(item.get('duration'))}\n"
        text += f"[📥 دریافت این آهنگ](send:{item['webpage_url']})\n"
        text += "〰️〰️〰️〰️〰️〰️\n"
    return text

# =================== هندلر Broadcast ==================
@bot.on_message(chat(BROADCAST_CHANNEL_ID))
async def channel_broadcast_handler(client, message):
    logger.info(f"New message in broadcast channel {BROADCAST_CHANNEL_ID}")
    users = db.run_query("SELECT chat_id FROM users", fetch=True)
    success_count = 0
    for u in users:
        try:
            await client.forward_message(
                chat_id=u['chat_id'],
                from_chat_id=message.chat.id,
                message_id=message.id
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to forward message to {u['chat_id']}: {e}")
    logger.info(f"Broadcast finished. Sent to {success_count} users.")

# =================== هندلر دستورات ==================
@bot.on_message(command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await client.get_me()).username
    
    if message.chat.type == "private":
        track_user(message.chat.id)

    await message.reply("🎶 *به ربات دانلودر ساندکلاود خوش آمدید!*\n\n🔗 لینک آهنگ را بفرستید یا نام آن را برای جستجو ارسال کنید.\nبرای راهنما /help را بزنید.")

@bot.on_message(command("help"))
async def help_handler(client, message):
    text = (
        "💡 *راهنمای استفاده:*\n\n"
        "1️⃣ **دانلود با لینک:** لینک آهنگ ساندکلاود (حتی لینک‌های on.soundcloud.com) را در ربات بفرستید.\n"
        "2️⃣ **جستجو:** نام آهنگ یا خواننده را تایپ کرده و ارسال کنید تا ربات برای شما جستجو کند.\n\n"
        "برای مشاهده آمار ربات از /stats استفاده کنید."
    )
    await message.reply(text)

@bot.on_message(command("stats"))
async def stats_handler(client, message):
    users_count = db.run_query("SELECT COUNT(chat_id) as c FROM users", fetchone=True).get('c', 0)
    tracks_count = db.run_query("SELECT COUNT(uuid) as c FROM tracks", fetchone=True).get('c', 0)
    await message.reply(f"📊 *آمار ربات:*\n\n👥 کل کاربران: `{users_count}`\n🎵 آهنگ‌های ذخیره‌شده: `{tracks_count}`")

# =================== هندلر متنی ==================
@bot.on_message(text)
async def handle_text(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME: 
        BOT_USERNAME = (await client.get_me()).username
    
    # فیلتر کردن دستورات برای اینکه با جستجو تداخل نداشته باشند
    if message.text.startswith("/"): return

    if message.chat.type == "private":
        track_user(message.chat.id)
        
    content = message.text.strip()
    
    if message.chat.type != "private":
        mention = f"@{BOT_USERNAME}"
        if mention not in content.lower() and "soundcloud.com" not in content.lower(): return
        content = content.replace(mention, "").strip()
        if not content: return

    # بهبود Regex برای پشتیبانی از لینک‌های کوتاه شده
    url_match = re.search(r"(https?://(?:on\.|m\.|www\.)?soundcloud\.com/[^\s]+)", content)
    
    if url_match:
        url = url_match.group(1).split('?')[0]
        
        logger.info(f"Processing URL: {url} by user {message.author.id}")
        msg = await message.reply("⏳ در حال استخراج اطلاعات از ساندکلاود...")
        
        # چک کردن کش فقط برای لینک‌های استاندارد انجام می‌شود تا لینک کوتاه شده ریکوئست شود
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
                return await msg.edit_text("❌ خطا در دریافت اطلاعات. بررسی کنید لینک معتبر باشد.")

            track_id = info.get('id', 'unknown')
            clean_url = info.get("webpage_url", url).split('?')[0]
            
            # در صورتی که لینک اولیه کوتاه شده بود، کش را با لینک اصلی دوباره بررسی میکنیم
            cached_track2 = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (clean_url,), fetchone=True)
            if cached_track2:
                meta = cached_track2
            else:
                meta = {
                    "uuid": f"sc_{track_id}",
                    "title": info.get("title", "نامشخص"),
                    "uploader": info.get("uploader", "نامشخص"),
                    "genre": info.get("genre", "نامشخص"),
                    "upload_date": str(info.get("upload_date", ""))[:4],
                    "webpage_url": clean_url,
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": format_duration(info.get("duration", 0)),
                }
                placeholders = ','.join(['?'] * len(meta))
                db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({placeholders})", tuple(meta.values()))
            
            await msg.delete()
            
        caption = build_caption(meta, BOT_USERNAME)
        buttons = [[InlineKeyboardButton("⬇️ دریافت فایل صوتی", callback_data=f"getaudio:{track_id}")]]
        
        if meta.get("thumbnail"):
            await client.send_photo(message.chat.id, meta["thumbnail"], caption=caption, reply_markup=InlineKeyboard(*buttons))
        else:
            await client.send_message(message.chat.id, caption, reply_markup=InlineKeyboard(*buttons))
        return

    # بخش جستجو
    logger.info(f"Searching SoundCloud for: {content} by user {message.author.id}")
    msg = await message.reply(f"🔍 در حال جستجو برای `{content}` ...")
    try:
        results = await search_soundcloud(content, 10)
    except Exception as e:
        logger.error(f"Search error for query '{content}': {e}")
        await msg.delete()
        return await message.reply("❌ متاسفانه هنگام جستجو خطایی رخ داد.")

    if not results:
        await msg.delete()
        return await message.reply("😔 موردی با این نام یافت نشد.")

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

    if data == "ignore":
        return await callback_query.answer("صبور باشید...")

    if data.startswith("getaudio:"):       
        parts = data.split(":")
        if len(parts) < 2: return
        track_id = parts[1]
        
        await callback_query.answer("⏳ در حال پردازش...")

        try:
            downloading_keyboard = InlineKeyboard(
                [InlineKeyboardButton("⏳ در حال دریافت از سرور...", callback_data="ignore")]
            )
            downloading_text = "⏳ *در حال دانلود و آماده‌سازی فایل از سرورهای ساندکلاود...*\nلطفا صبور باشید."
            
            if callback_query.message.photo:
                await client.edit_message_caption(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.id,
                    caption=downloading_text,
                    reply_markup=downloading_keyboard
                )
            else:
                await client.edit_message_text(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.id,
                    text=downloading_text,
                    reply_markup=downloading_keyboard
                )
        except Exception as e:
            logger.error(f"Failed to update message UI to 'downloading': {e}")
        
        row = db.run_query("SELECT * FROM tracks WHERE uuid=?", (f"sc_{track_id}",), fetchone=True)
        if not row:
            return await callback_query.message.reply("❌ اطلاعات این آهنگ منقضی شده است. لطفا دوباره لینک را بفرستید.")

        caption = build_caption(row, BOT_USERNAME)
        msg_to_delete = callback_query.message
        url = row.get("webpage_url")

        if row.get("cache_msg_id"):
            try:
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
            await msg_to_delete.delete()
            return await callback_query.message.reply("❌ خطا در دانلود فایل از سرور. ممکن است فایل محدود شده باشد.")

        try:
            with open(filepath, "rb") as f:
                sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f, title=row['title'], caption=caption)
            
            msg_id = sent_msg.id
            if msg_id:
                row["cache_msg_id"] = str(msg_id)
                placeholders = ','.join(['?'] * len(row))
                db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(row.keys())}) VALUES ({placeholders})", tuple(row.values()))
            
            await client.forward_message(
                chat_id=callback_query.message.chat.id,
                from_chat_id=CACHE_CHANNEL_ID,
                message_id=msg_id
            )
            await msg_to_delete.delete()
            
        except Exception as e:
            logger.error(f"Upload/Forward error: {e}")
            await callback_query.message.reply("❌ خطا در آپلود یا ارسال فایل.")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run()
