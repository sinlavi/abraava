import os
import sqlite3
import asyncio
import re
import aiohttp
from pathlib import Path

from balethon import Client
from balethon.conditions import document, private, command, text, audio
from balethon.objects import InlineKeyboard, ReplyKeyboard

from mutagen import File
import yt_dlp

# ================= تنظیمات اصلی ربات =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "-1000000000000"))                                # آیدی عددی کانال آرشیو

AUDIO_EXTENSIONS = {'mp3', 'm4a', 'wav', 'ogg', 'flac', 'amr', 'wma'}
TEMP_DIR = Path(os.path.abspath("temp_uploads"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "audio_metadata.db"

bot = Client(BOT_TOKEN)
BOT_USERNAME = "" # در تابع استارت مقداردهی می‌شود

# ================= مدیریت دیتابیس =================
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

# در کلاس DatabaseManager تغییر در init_db و ساختار جدول:

def init_db(self):
    with sqlite3.connect(self.db_path) as conn:
        c = conn.cursor()

        # ساخت یا اصلاح جدول با ستون‌های کامل
        c.execute('''
            CREATE TABLE IF NOT EXISTS audio_metadata (
                uuid TEXT PRIMARY KEY,
                track_number TEXT,
                title TEXT,
                artist TEXT,
                album TEXT,
                genre TEXT,
                comment TEXT,
                url TEXT,
                album_artist TEXT,
                disk_number TEXT,
                year TEXT,
                copyright TEXT,
                publisher TEXT,
                composer TEXT,
                conductor TEXT,
                encoded_by TEXT,
                mood TEXT,
                catalog TEXT,
                user_rating INTEGER,
                track_gain REAL,
                album_gain REAL,
                part_of_compilation TEXT,
                isrc TEXT,
                channel_message_id TEXT,
                uploader_name TEXT
            )
        ''')
        conn.commit()

    def run_query(self, query, params=(), fetch=False, fetchone=False):
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(query, params)
            if fetchone:
                return dict(c.fetchone() or {})
            if fetch:
                return [dict(row) for row in c.fetchall()]
            conn.commit()

db = DatabaseManager(DB_PATH)

# ================= توابع کمکی =================
def extract_file_metadata(filepath):
    try:
        audio_file = File(filepath)
        if not audio_file or not audio_file.tags:
            return {}

        tags = audio_file.tags
        result = {}

        # تعریف کلیدهای استاندارد متادیتا که می‌خواهیم استخراج کنیم
        tag_keys = {
            "title": ["TIT2", "©nam", "title", "\xa9nam"],
            "artist": ["TPE1", "©ART", "artist", "\xa9ART"],
            "album": ["TALB", "©alb", "album", "\xa9alb"],
            "genre": ["TCON", "genre", "©gen"],
            "year": ["TDRC", "TYER", "date", "©day", "\xa9day"],
            "comment": ["COMM::eng", "©cmt", "comment"],
            "track_number": ["TRCK", "tracknumber", "track"],
            "album_artist": ["TPE2", "aART", "©ART"],
            "disk_number": ["TPOS"],
            "copyright": ["TCOP"],
            "publisher": ["TPUB"],
            "composer": ["TCOM"],
            "conductor": ["TPE3"],
            "encoded_by": ["TENC"],
            "mood": ["TMOO"],
            "catalog": ["TXXX:CATALOGNUMBER"],
            "isrc": ["TSRC"],
            "key": ["TKEY"],
            "bpm": ["TBPM"]
        }


        def try_get(tag_name):
            # جستجو در تگ‌ها از لیست کلیدها
            for key in tag_name:
                if key in tags:
                    value = tags.get(key)
                    if not value:
                        continue
                    # بعضی مقادیر ممکن است لیست باشند یا نمونه‌های مختلف کلاس‌ها
                    if hasattr(value, "text"):
                        # ID3 frame
                        try:
                            return str(value.text[0])
                        except Exception:
                            return str(value)
                    elif isinstance(value, (list, tuple)):
                        # لیست مقدار
                        try:
                            return str(value[0])
                        except:
                            return str(value)
                    elif isinstance(value, bytes):
                        # داده باینری با احتمال encoding خاص
                        try:
                            return value.decode('utf-8', errors='ignore').strip()
                        except:
                            return str(value)
                    else:
                        return str(value).strip()
            return None

        for key, keys_list in tag_keys.items():
            val = try_get(keys_list)
            if val:
                result[key] = val

        return result
    except Exception as e:
        print(f"extract_file_metadata error: {e}")
        return {}

def get_uploader_name(author):
    if author.username:
        return f"@{author.username}"
    return author.first_name or "کاربر ناشناس"

def build_metadata_dict(base_meta, yt_dlp_meta=None):
    result = {k: "" for k in [
        "uuid", "title", "artist", "album", "genre", "year", "comment",
        "url", "album_artist", "disk_number", "copyright",
        "publisher", "composer", "conductor", "encoded_by",
        "mood", "catalog", "part_of_compilation", "isrc",
        "key", "bpm", "channel_message_id", "uploader_name"
    ]}

    result.update({"user_rating": 0, "track_gain": 0.0, "album_gain": 0.0})

    for k, v in base_meta.items():
        if v:
            result[k] = str(v).strip()

    if yt_dlp_meta:
        # پر کردن متادیتا از yt_dlp اگر در دسترس بود
        result['title'] = result.get('title') or yt_dlp_meta.get('title', '')
        result['artist'] = result.get('artist') or yt_dlp_meta.get('uploader', '')
        result['genre'] = result.get('genre') or yt_dlp_meta.get('genre', '')
        result['url'] = yt_dlp_meta.get('webpage_url', '')

    return result

async def save_to_db(metadata: dict):
    loop = asyncio.get_event_loop()
    def _save():
        exists = db.run_query("SELECT 1 FROM audio_metadata WHERE uuid = ?", (metadata["uuid"],), fetchone=True)
        if not exists:
            db.run_query(f'''
                INSERT INTO audio_metadata ({", ".join(metadata.keys())}) 
                VALUES ({", ".join([f":{k}" for k in metadata.keys()])})
            ''', metadata)
        else:
            db.run_query("UPDATE audio_metadata SET channel_message_id = ?, uploader_name = ? WHERE uuid = ?",
                         (metadata.get("channel_message_id"), metadata.get("uploader_name"), metadata["uuid"]))
    await loop.run_in_executor(None, _save)

def build_metadata_text(metadata: dict):
    """ساخت کپشن زیبا برای موزیک"""
    title = metadata.get("title") or "نامشخص"
    artist = metadata.get("artist") or "نامشخص"

    lines = [
        f"🎧 *{title}*",
        f"🎤 هنرمند: *{artist}*",
        "━━━━━━━━━━━━"
    ]

    if metadata.get("album"): lines.append(f"💿 آلبوم: {metadata['album']}")
    if metadata.get("genre"): lines.append(f"🎸 ژانر: {metadata['genre']}")
    if metadata.get("year"): lines.append(f"📅 سال انتشار: {metadata['year']}")
    if metadata.get("url"): lines.append(f"🔗 لینک اصلی: [کلیک کنید]({metadata['url']})")

    lines.append("━━━━━━━━━━━━")
    uploader = metadata.get("uploader_name", "سیستم")
    lines.append(f"👤 آرشیو شده توسط: {uploader}")
    lines.append("🤖 @abraava_bot") # یوزرنیم ربات خودتون رو جایگزین کنید

    return "\n".join(lines)

# ================= دانلودر ساندکلاود =================
def download_soundcloud_track(url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(TEMP_DIR / '%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        return filepath, info

# ================= دانلود جزئی فایل از بله =================
async def download_partial_file(client, file_id, save_path, chunk_size=1024*2047):
    """دانلود 512 کیلوبایت اول فایل برای خواندن سریع متادیتا بدون مصرف حجم"""
    try:
        file_info = await client.get_file(file_id)
        # آدرس دانلود فایل در بله
        url = f"https://tapi.bale.ai/file/bot{BOT_TOKEN}/{file_info.id}"

        async with aiohttp.ClientSession() as session:
            headers = {"Range": f"bytes=0-{chunk_size}"}
            async with session.get(url, headers=headers) as resp:
                data = await resp.read()
                with open(save_path, "wb") as f:
                    f.write(data)
                return True
    except Exception as e:
        print(f"Partial download failed: {e}")
        return False

# ================= هندلرهای ربات =================

@bot.on_message(private & command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    me = await client.get_me()
    BOT_USERNAME = me.username

    keyboard = ReplyKeyboard(["🔍 جستجوی پیشرفته", "ℹ️ راهنما"])
    welcome_text = (
        "✨ **به ربات هوشمند آرشیو موزیک خوش آمدید!** ✨\n\n"
        "🎧 من اینجا هستم تا بهترین آرشیو موزیک را برای شما بسازم.\n"
        "شما می‌توانید **فایل‌های صوتی** خود را به صورت مستقیم ارسال کنید یا **لینک SoundCloud** بفرستید تا در کانال با اطلاعات کامل ذخیره شوند.\n\n"
        "📌 *نکته:* من را می‌توانید به گروه‌های خود اضافه کنید تا آهنگ‌های ارسالی را به صورت خودکار شناسایی و آرشیو کنم!"
    )
    await message.reply(welcome_text, keyboard)

@bot.on_message(text)
async def text_handler(client, message):
    text_content = message.text
    is_group = message.chat.type in ["group", "supergroup"]

    # در گروه‌ها، اگر ربات منشن نشده باشد و لینک ساندکلاود نباشد کاری نکن
    if is_group:
        if BOT_USERNAME and f"@{BOT_USERNAME}" not in text_content and "soundcloud.com" not in text_content:
            return
        text_content = text_content.replace(f"@{BOT_USERNAME}", "").strip()

    if text_content.startswith("ℹ️ راهنما") or text_content == "/help":
        help_text = (
            "**📚 راهنمای استفاده از ربات:**\n\n"
            "📤 **آپلود سریع:** کافیه فایل صوتی یا لینک SoundCloud رو برام بفرستی.\n"
            "گروه‌ها: توی گروه‌ها اگه من رو ادد کنی، هر موزیکی فرستاده بشه رو خودکار آرشیو می‌کنم. برای لینک ساندکلاود باید من رو روی پیام ریپلای یا منشن کنی.\n"
            "🔍 **جستجو:** نام خواننده، آهنگ یا آلبوم رو بفرست تا تو کسری از ثانیه پیداش کنم."
        )
        return await message.reply(help_text)

    # بررسی لینک ساندکلاود
    if "soundcloud.com" in text_content:
        msg = await message.reply("⏳ *در حال ارتباط با سرورهای SoundCloud...* لطفاً کمی منتظر بمانید 🎧")
        url_match = re.search(r'(https?://[^\s]+)', text_content)
        if not url_match: return
        url = url_match.group(1)

        loop = asyncio.get_event_loop()
        try:
            filepath, yt_info = await loop.run_in_executor(None, download_soundcloud_track, url)
            file_meta = extract_file_metadata(filepath)

            metadata = build_metadata_dict(file_meta, yt_info)
            metadata["uuid"] = f"sc_{yt_info['id']}"
            metadata["uploader_name"] = get_uploader_name(message.author)

            caption_text = build_metadata_text(metadata)
            sent_message = await client.send_audio(DB_CHANNEL_ID, filepath, caption=caption_text)
            metadata["channel_message_id"] = sent_message.document.id

            await save_to_db(metadata)
            await msg.edit_text("✅ موزیک شما با موفقیت از ساندکلاود دریافت و در آرشیو ثبت شد! 🎉")

            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            await msg.edit_text("❌ متأسفانه در دریافت لینک مشکلی پیش آمد. بررسی کنید لینک معتبر باشد.")
        return

    # جستجوی هوشمند
    if text_content in ["🔍 جستجوی پیشرفته", "/search"]:
        return await message.reply("لطفاً نام خواننده، آلبوم یا آهنگ مورد نظرتان را تایپ کنید 🔎:")

    if not text_content.startswith("/") and not is_group:
        keyword = text_content
        buttons = InlineKeyboard(
            [("🎵 جستجو در نام آهنگ‌ها", f"srch:track:{keyword}")],
            [("🎤 جستجو در خواننده‌ها", f"srch:artist:{keyword}")],
            [("💿 جستجو در آلبوم‌ها", f"srch:album:{keyword}")]
        )
        await message.reply(f"🔎 می‌خواهید عبارت **{keyword}** را در کدام بخش جستجو کنم؟", buttons)

@bot.on_message(document | audio)
async def handle_document(client, message):
    # دریافت نوع فایل. بله فایل‌های صوتی را گاهی به عنوان document می‌فرستد
    doc = getattr(message, 'document', None) or getattr(message, 'audio', None)
    if not doc: return

    mime_type = getattr(doc, 'mime_type', '')
    file_type = mime_type.split("/")[-1].split(";")[0] if mime_type else 'mp3'

    if file_type not in AUDIO_EXTENSIONS and "audio" not in mime_type:
        # در گروه پیام خطا ندهیم تا مزاحمت ایجاد نکند
        if message.chat.type == "private":
            await message.reply("❌ فرمت فایل مجاز نیست. لطفاً فقط فایل‌های صوتی ارسال کنید.")
        return

    msg = await message.reply("⚡ *در حال استخراج اطلاعات فایل...*")
    filename = doc.id.replace(":", "_") + f".{file_type}"
    tmp_path = TEMP_DIR / filename

    try:
        # دانلود جزئی (فقط 512 کیلوبایت اول برای متادیتا)
        success = await download_partial_file(client, doc.id, str(tmp_path))
        if not success:
            # اگر دانلود جزئی کار نکرد، فایل کامل دانلود شود
            response = await client.download(doc.id)
            tmp_path.write_bytes(response)

        file_meta = extract_file_metadata(str(tmp_path))
        metadata = build_metadata_dict(file_meta)
        metadata["uuid"] = filename
        metadata["uploader_name"] = get_uploader_name(message.author)

        # اگر متادیتا نام خواننده نداشت، از نام فایل در صورت امکان استفاده کن
        if not metadata.get("title"):
            metadata["title"] = getattr(doc, 'file_name', 'موزیک ناشناس').replace(f".{file_type}", "")

        caption_text = build_metadata_text(metadata)

        # فوروارد فایل اصلی به کانال (نیاز به آپلود مجدد نیست، آیدی فایل کافیست)
        sent_message = await client.send_document(DB_CHANNEL_ID, doc.id, caption=caption_text)
        metadata["channel_message_id"] = sent_message.document.id

        await save_to_db(metadata)
        await msg.edit_text("✅ موزیک شناسایی و با موفقیت در آرشیو ثبت شد! 🎶")

    except Exception as e:
        await msg.edit_text(f"❌ خطایی رخ داد: {e}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

@bot.on_callback_query()
async def handle_callback(client, callback_query):
    data = callback_query.data
    loop = asyncio.get_event_loop()

    if data.startswith("srch:"):
        _, search_type, keyword = data.split(":", 2)

        def do_search():
            if search_type == "track":
                return db.run_query("SELECT uuid, title, artist FROM audio_metadata WHERE title LIKE ? OR artist LIKE ? LIMIT 10", (f"%{keyword}%", f"%{keyword}%"), fetch=True)
            elif search_type == "album":
                return db.run_query("SELECT DISTINCT album, artist FROM audio_metadata WHERE album LIKE ? AND album != '' LIMIT 10", (f"%{keyword}%",), fetch=True)
            elif search_type == "artist":
                return db.run_query("SELECT DISTINCT artist FROM audio_metadata WHERE artist LIKE ? AND artist != '' LIMIT 10", (f"%{keyword}%",), fetch=True)

        results = await loop.run_in_executor(None, do_search)

        if not results:
            return await callback_query.message.edit_text("😔 متأسفانه هیچ نتیجه‌ای پیدا نشد. عبارت دیگری را امتحان کنید.")

        buttons = []
        if search_type == "track":
            buttons = [[(f"🎧 {row.get('title','نامشخص')} - {row.get('artist','نامشخص')[:15]}", f"track:{row['uuid']}")] for row in results]
        elif search_type == "album":
            buttons = [[(f"💿 {row.get('album','')} - {row.get('artist','نامشخص')[:15]}", f"album_tracks:{row['album']}:{row['artist']}")] for row in results]
        elif search_type == "artist":
            buttons = [[(f"🎤 {row['artist']}", f"artist:{row['artist']}")] for row in results]

        await callback_query.message.edit_text(f"🎯 نتایج یافت شده برای **{keyword}**:", InlineKeyboard(*buttons))

    # بقیه هندلرهای دکمه‌های شیشه‌ای مانند قبل ...
    # (کد هندلرهای artist:, artist_albums: و track: به همین سبک می‌توانند بهبود یابند)
    elif data.startswith("track:"):
        uuid = data.split(":", 1)[1]
        row = await loop.run_in_executor(None, lambda: db.run_query("SELECT * FROM audio_metadata WHERE uuid = ?", (uuid,), fetchone=True))

        if not row or not row.get("channel_message_id"):
            return await callback_query.message.reply("❌ متأسفانه فایل در دیتابیس یافت نشد.")

        caption = build_metadata_text(row)
        await client.send_document(callback_query.message.chat.id, row["channel_message_id"], caption=caption)

if __name__ == "__main__":
    bot.run()
