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

TEMP_DIR = Path("temp_audio")
TEMP_DIR.mkdir(exist_ok=True)
DB_PATH = "cache.db"
COOKIES_FILE = "cookies.txt"  # می‌تواند از متغیر محیطی هم خوانده شود

bot = Client(BOT_TOKEN)
BOT_USERNAME = ""

# ===================== تنظیمات پایه‌ی yt-dlp =====================
YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
}
if os.path.exists(COOKIES_FILE):
    YDL_BASE_OPTS["cookiefile"] = COOKIES_FILE
    logger.info("Using cookies.txt for yt-dlp requests.")
else:
    logger.info("cookies.txt not found, continuing without cookies.")

# ===================== دیتابیس =====================
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        fields = [
            "uuid TEXT PRIMARY KEY",        # e.g., "sc_12345" or "yt_abcdef"
            "title TEXT",
            "uploader TEXT",
            "genre TEXT",
            "upload_date TEXT",
            "webpage_url TEXT",
            "thumbnail TEXT",
            "cache_msg_id TEXT",
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
    genre = track.get('genre')
    genre_line = f"🎸 ژانر: {genre}\n" if genre else ""
    return (
        f"🎧 *{track.get('title','نامشخص')}*\n"
        f"🎤 هنرمند: *{track.get('uploader','نامشخص')}*\n"
        f"📅 سال: {track.get('upload_date','نامشخص')}\n"
        f"{genre_line}"
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

# =================== توابع عمومی yt-dlp ==================
def fetch_info_sync(url):
    """دریافت اطلاعات یک لینک (ساندکلاود یا یوتیوب) بدون دانلود"""
    opts = {**YDL_BASE_OPTS, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def download_audio_sync(url):
    """دانلود بهترین صوت و تبدیل به mp3 با ffmpeg"""
    opts = {
        **YDL_BASE_OPTS,
        "format": "bestaudio/best",
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = str(TEMP_DIR / f"{info['id']}.mp3")
        return filepath, info

async def fetch_info(url):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_info_sync, url)

async def download_audio(url):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_audio_sync, url)

# =================== جستجوی یوتیوب موزیک ==================
def search_youtube_music_sync(query, max_results=10):
    results = []
    opts = {**YDL_BASE_OPTS, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        for e in info.get("entries", []):
            results.append({
                "id": e.get("id"),
                "title": e.get("title", "بدون نام"),
                "uploader": e.get("uploader", "نامشخص"),
                "webpage_url": e.get("webpage_url", "") or f"https://music.youtube.com/watch?v={e.get('id')}",
                "thumbnail": e.get("thumbnail", ""),
                "duration": e.get("duration", 0),
                "source": "yt"  # برای شناسایی منبع
            })
    return results

async def search_youtube_music(query, max_results=10):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_youtube_music_sync, query, max_results)

def get_search_text(results):
    text = "🔍 *نتایج جستجو (یوتیوب موزیک):*\n\n"
    for item in results:
        text += f"👤 {item['uploader']}\n"
        text += f"🎵 {item['title']}\n"
        text += f"⏱️ {format_duration(item.get('duration'))}\n"
        text += f"[📥 دریافت این آهنگ](send:{item['webpage_url']})\n"
        text += "〰️〰️〰️〰️〰️〰️\n"
    return text

# =================== ذخیره‌سازی اطلاعات در دیتابیس ==================
def store_track_meta(meta: dict):
    """meta باید کلیدهای: uuid, title, uploader, genre, upload_date,
       webpage_url, thumbnail, duration را داشته باشد"""
    placeholders = ','.join(['?'] * len(meta))
    db.run_query(
        f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({placeholders})",
        tuple(meta.values())
    )

def extract_year(info_dict):
    upload_date = info_dict.get("upload_date", "")
    if upload_date and len(upload_date) >= 4:
        return upload_date[:4]
    # برخی استخراج‌کننده‌ها year دارند
    year = info_dict.get("year")
    if year:
        return str(year)
    return "نامشخص"

def extract_genre(info_dict):
    # برای ساندکلاود genre مستقیم دارد، برای یوتیوب از tags یا categories
    genre = info_dict.get("genre")
    if genre:
        return genre
    tags = info_dict.get("tags")
    if tags and isinstance(tags, list) and len(tags) > 0:
        return tags[0]  # اولین تگ
    categories = info_dict.get("categories")
    if categories and isinstance(categories, list) and len(categories) > 0:
        return categories[0]
    return None

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
    await message.reply(
        "🎶 *به ربات دانلودر موزیک خوش آمدید!*\n\n"
        "🔗 لینک یوتیوب / یوتیوب موزیک / ساندکلاود را بفرستید "
        "یا نام آهنگ را برای جستجو در **یوتیوب موزیک** ارسال کنید.\n"
        "برای راهنما /help را بزنید."
    )

@bot.on_message(command("help"))
async def help_handler(client, message):
    text = (
        "💡 *راهنمای استفاده:*\n\n"
        "1️⃣ **دانلود با لینک:** لینک آهنگ از ساندکلاود، یوتیوب یا یوتیوب موزیک را بفرستید.\n"
        "2️⃣ **جستجو:** نام آهنگ یا خواننده را تایپ کنید. ربات در یوتیوب موزیک جستجو می‌کند.\n\n"
        "برای مشاهده آمار ربات از /stats استفاده کنید."
    )
    await message.reply(text)

@bot.on_message(command("stats"))
async def stats_handler(client, message):
    users_count = db.run_query("SELECT COUNT(chat_id) as c FROM users", fetchone=True).get('c', 0)
    tracks_count = db.run_query("SELECT COUNT(uuid) as c FROM tracks", fetchone=True).get('c', 0)
    await message.reply(
        f"📊 *آمار ربات:*\n\n👥 کل کاربران: `{users_count}`\n🎵 آهنگ‌های ذخیره‌شده: `{tracks_count}`"
    )

# =================== هندلر متنی (لینک‌ها و جستجو) ==================
@bot.on_message(text)
async def handle_text(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await client.get_me()).username

    # فیلتر دستورات
    if message.text.startswith("/"):
        return

    if message.chat.type == "private":
        track_user(message.chat.id)

    content = message.text.strip()

    # اگر در گروه است و منشن ربات ندارد و لینک هم ندارد نادیده بگیر
    if message.chat.type != "private":
        mention = f"@{BOT_USERNAME}"
        has_mention = mention in content.lower()
        has_link = "soundcloud.com" in content.lower() or "youtube.com" in content.lower() or "youtu.be" in content.lower()
        if not has_mention and not has_link:
            return
        content = content.replace(mention, "").strip()
        if not content:
            return

    # ---- شناسایی لینک ساندکلاود ----
    sc_match = re.search(r"(https?://(?:on\.|m\.|www\.)?soundcloud\.com/[^\s]+)", content)
    if sc_match:
        url = sc_match.group(1).split('?')[0]
        logger.info(f"Processing SoundCloud URL: {url}")
        msg = await message.reply("⏳ در حال استخراج اطلاعات از ساندکلاود...")

        # بررسی کش با URL اصلی
        cached_track = db.run_query(
            "SELECT * FROM tracks WHERE webpage_url=? AND uuid LIKE 'sc_%'",
            (url,), fetchone=True
        )
        if cached_track:
            meta = cached_track
            await msg.delete()
        else:
            try:
                info = await fetch_info(url)
            except Exception as e:
                logger.error(f"Error extracting info for {url}: {e}")
                await msg.edit_text("❌ خطا در دریافت اطلاعات. بررسی کنید لینک معتبر باشد.")
                return

            track_id = info.get('id', 'unknown')
            clean_url = info.get("webpage_url", url).split('?')[0]
            # اگر لینک کوتاه شده بود، دوباره کش را با clean_url چک کن
            cached_track2 = db.run_query(
                "SELECT * FROM tracks WHERE webpage_url=? AND uuid LIKE 'sc_%'",
                (clean_url,), fetchone=True
            )
            if cached_track2:
                meta = cached_track2
            else:
                meta = {
                    "uuid": f"sc_{track_id}",
                    "title": info.get("title", "نامشخص"),
                    "uploader": info.get("uploader", "نامشخص"),
                    "genre": info.get("genre", "نامشخص"),
                    "upload_date": extract_year(info),
                    "webpage_url": clean_url,
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": format_duration(info.get("duration", 0)),
                }
                store_track_meta(meta)
            await msg.delete()

        caption = build_caption(meta, BOT_USERNAME)
        buttons = [[InlineKeyboardButton("⬇️ دریافت فایل صوتی", callback_data=f"getaudio:sc_{meta['uuid'].split('_')[1]}")]]
        if meta.get("thumbnail"):
            await client.send_photo(message.chat.id, meta["thumbnail"], caption=caption, reply_markup=InlineKeyboard(*buttons))
        else:
            await client.send_message(message.chat.id, caption, reply_markup=InlineKeyboard(*buttons))
        return

    # ---- شناسایی لینک یوتیوب / یوتیوب موزیک ----
    yt_match = re.search(
        r"(https?://(?:www\.|m\.|music\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)",
        content
    )
    if yt_match:
        url = yt_match.group(0).split('?')[0]
        # تبدیل لینک youtu.be به فرم کامل برای استخراج v
        if "youtu.be" in url:
            # یوتیوب کوتاه: id در انتهای مسیر است
            pass  # yt-dlp خودش هندل می‌کند
        logger.info(f"Processing YouTube URL: {url}")
        msg = await message.reply("⏳ در حال استخراج اطلاعات از یوتیوب...")

        # بررسی کش
        cached_track = db.run_query(
            "SELECT * FROM tracks WHERE webpage_url=? AND uuid LIKE 'yt_%'",
            (url,), fetchone=True
        )
        if cached_track:
            meta = cached_track
            await msg.delete()
        else:
            try:
                info = await fetch_info(url)
            except Exception as e:
                logger.error(f"Error extracting info for {url}: {e}")
                await msg.edit_text("❌ خطا در دریافت اطلاعات از یوتیوب.")
                return

            track_id = info.get('id', 'unknown')
            clean_url = info.get("webpage_url", url)
            # دوباره کش با clean_url چک کن (ممکن است لینک کوتاه شده باشد)
            cached_track2 = db.run_query(
                "SELECT * FROM tracks WHERE webpage_url=? AND uuid LIKE 'yt_%'",
                (clean_url,), fetchone=True
            )
            if cached_track2:
                meta = cached_track2
            else:
                genre = extract_genre(info)
                meta = {
                    "uuid": f"yt_{track_id}",
                    "title": info.get("title", "نامشخص"),
                    "uploader": info.get("uploader", info.get("channel", "نامشخص")),
                    "genre": genre if genre else "",
                    "upload_date": extract_year(info),
                    "webpage_url": clean_url,
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": format_duration(info.get("duration", 0)),
                }
                store_track_meta(meta)
            await msg.delete()

        caption = build_caption(meta, BOT_USERNAME)
        buttons = [[InlineKeyboardButton("⬇️ دریافت فایل صوتی", callback_data=f"getaudio:yt_{meta['uuid'].split('_')[1]}")]]
        if meta.get("thumbnail"):
            await client.send_photo(message.chat.id, meta["thumbnail"], caption=caption, reply_markup=InlineKeyboard(*buttons))
        else:
            await client.send_message(message.chat.id, caption, reply_markup=InlineKeyboard(*buttons))
        return

    # ---- جستجوی یوتیوب موزیک (پیش‌فرض) ----
    logger.info(f"YouTube Music search for: {content}")
    msg = await message.reply(f"🔍 در حال جستجو در یوتیوب موزیک برای `{content}` ...")
    try:
        results = await search_youtube_music(content, 10)
    except Exception as e:
        logger.error(f"Search error for '{content}': {e}")
        await msg.delete()
        await message.reply("❌ متاسفانه هنگام جستجو خطایی رخ داد.")
        return

    if not results:
        await msg.delete()
        await message.reply("😔 موردی با این نام یافت نشد.")
        return

    # برای کلیک روی لینک‌ها در متن جستجو، callback_data نمی‌توان در متن معمولی استفاده کرد،
    # پس از دکمه‌های inline برای هر نتیجه استفاده می‌کنیم
    # اما روش فعلی از send: در متن استفاده می‌کند که در بالهتون معتبر نیست.
    # بهتر است یک پیام با دکمه‌های inline و لیست نتایج ساخته شود.
    # اینجا یک روش ساده: ارسال نتایج به صورت متنی که هر آیتم یک دکمه دریافت صوت ندارد.
    # ولی کاربر انتظار دارد روی هر خط کلیک کند.
    # برای سادگی، یک کیبورد inline با شماره‌گذاری می‌سازیم.
    # اما get_search_text فعلی از send: پروتکل استفاده می‌کند که کار نمی‌کند.
    # بهتر است inline keyboard با callback_data برای هر نتیجه ساخته شود.

    # بازنویسی: ساخت کیبورد inline با 5 ردیف حداکثر
    keyboard_rows = []
    for i, item in enumerate(results[:10]):
        label = f"{i+1}. {item['title'][:30]} - {item['uploader'][:20]}"
        # callback_data محدودیت طول دارد، بهتر است فقط id رد شود
        cb_data = f"dlresult:yt_{item['id']}"
        keyboard_rows.append([InlineKeyboardButton(label, callback_data=cb_data)])

    text = f"🔍 *نتایج جستجو برای:* `{content}`\n\nیک گزینه را انتخاب کنید:"
    await msg.delete()
    await message.reply(text, reply_markup=InlineKeyboard(*keyboard_rows))
    return

# =================== هندلر callback برای دریافت فایل ==================
@bot.on_callback_query()
async def handle_callback(client, callback_query):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await client.get_me()).username

    data = callback_query.data

    if data == "ignore":
        return await callback_query.answer("صبور باشید...")

    # دریافت فایل از نتیجه جستجو (new result download)
    if data.startswith("dlresult:"):
        parts = data.split(":", 1)
        if len(parts) < 2:
            return await callback_query.answer("داده نامعتبر است.")
        uuid = parts[1]  # e.g., yt_abcd123
        track_id = uuid.split("_", 1)[1] if "_" in uuid else uuid
        await callback_query.answer("⏳ در حال پردازش...")
        await process_audio_download(client, callback_query, uuid, track_id)
        return

    # دریافت فایل از دکمه "دریافت فایل صوتی"
    if data.startswith("getaudio:"):
        parts = data.split(":")
        if len(parts) < 2:
            return await callback_query.answer("داده نامعتبر است.")
        # انتظار می‌رود فرمت "getaudio:sc_12345" یا "getaudio:yt_abcdef"
        # اما در کد دکمه‌ها فقط id بدون پیشوند فرستاده شده بود. اصلاح می‌کنیم.
        # در هندلر لینک‌ها، callback_data را به صورت getaudio:sc_12345 تنظیم می‌کنیم.
        # اینجا track_id را کامل می‌گیریم.
        full_id = parts[1]  # e.g., sc_12345
        if "_" in full_id:
            uuid = full_id
            track_id = full_id.split("_", 1)[1]
        else:
            # fallback: ممکن است قدیمی باشد
            uuid = full_id
            track_id = full_id
        await callback_query.answer("⏳ در حال پردازش...")
        await process_audio_download(client, callback_query, uuid, track_id)
        return

async def process_audio_download(client, callback_query, uuid, track_id):
    """دانلود و ارسال فایل صوتی برای uuid خاص"""
    try:
        downloading_keyboard = InlineKeyboard(
            [InlineKeyboardButton("⏳ در حال دریافت از سرور...", callback_data="ignore")]
        )
        downloading_text = "⏳ *در حال دانلود و آماده‌سازی فایل...*\nلطفا صبور باشید."
        # ویرایش پیام اصلی
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
        logger.error(f"Failed to update message to 'downloading': {e}")

    row = db.run_query("SELECT * FROM tracks WHERE uuid=?", (uuid,), fetchone=True)
    if not row:
        try:
            await callback_query.message.reply("❌ اطلاعات این آهنگ منقضی شده است. لطفا دوباره لینک را بفرستید.")
        except:
            pass
        return

    caption = build_caption(row, BOT_USERNAME)
    msg_to_delete = callback_query.message
    url = row.get("webpage_url")

    # بررسی کش کانال
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
        filepath, info = await loop.run_in_executor(None, download_audio_sync, url)
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        await msg_to_delete.delete()
        await callback_query.message.reply("❌ خطا در دانلود فایل. ممکن است محدودیت منطقه‌ای وجود داشته باشد.")
        return

    try:
        with open(filepath, "rb") as f:
            sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f,
                                              title=row['title'],
                                              caption=caption)
        msg_id = sent_msg.id
        if msg_id:
            row["cache_msg_id"] = str(msg_id)
            placeholders = ','.join(['?'] * len(row))
            db.run_query(
                f"INSERT OR REPLACE INTO tracks ({','.join(row.keys())}) VALUES ({placeholders})",
                tuple(row.values())
            )

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

# =================== اجرای ربات ==================
if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run()
