import asyncio
import os
import re
import sqlite3
from pathlib import Path
import yt_dlp
from balethon import Client
from balethon.conditions import command, text
from balethon.objects import InlineKeyboard

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

async def search_soundcloud(query, max_results=30):
    results = []
    ydl_opts = {"quiet": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
        for e in info.get("entries", []):
            results.append({
                "id": e.get("id"),
                "title": e.get("title", "بدون نام"),
                "uploader": e.get("uploader", "نامشخص"),
                "webpage_url": e.get("webpage_url", ""),
                "thumbnail": e.get("thumbnail", ""),
                "duration": e.get("duration", 0)
            })
    return results

def get_search_text(results, page, total_pages):
    text = ""
    for item in results:
        text += f"👤 {item['uploader']}\n"
        text += f"🎵 {item['title']}\n"
        text += f"⏱️ {format_duration(item.get('duration'))}\n"
        text += f"[📥 دریافت](send:{item['webpage_url']})\n\n"
    text += f"📄 صفحه {page} از {total_pages}"
    return text

# =================== هندلر start ==================
@bot.on_message(command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = (await client.get_me()).username
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

    # هندل کردن لینک مستقیم
    if "soundcloud.com" in content:
        url_match = re.search(r"(https?://[^\s]+)", content)
        if not url_match: return await message.reply("❌ لینک نامعتبر!")
        url = url_match.group(1)
        
        msg = await message.reply("⏳ در حال دریافت اطلاعات...")
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, get_soundcloud_info, url)
        except Exception as e:
            return await msg.edit_text(f"❌ خطا در دریافت اطلاعات: {e}")

        track_id = info.get('id', 'unknown')
        meta = {
            "uuid": f"sc_{track_id}",
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "genre": info.get("genre", ""),
            "upload_date": str(info.get("upload_date", ""))[:4],
            "webpage_url": info.get("webpage_url", url),
            "thumbnail": info.get("thumbnail", ""),
            "duration": format_duration(info.get("duration", 0)),
        }
        
        # ذخیره ایمن در دیتابیس
        placeholders = ','.join(['?'] * len(meta))
        db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({placeholders})", tuple(meta.values()))
        
        caption = build_caption(meta, BOT_USERNAME)
        button = []
        button.append([("⬇️ دریافت فایل صوتی", f"getaudio:{track_id}")])
        
        await msg.delete()
        if meta["thumbnail"]:
            await client.send_photo(message.chat.id, meta["thumbnail"], caption=caption, reply_markup=InlineKeyboard(*buttons))
        else:
            await client.send_message(message.chat.id, caption, reply_markup=InlineKeyboard(*buttons))
        return

    # جستجوی متنی
    msg = await message.reply("🔍 در حال جستجو...")
    results = await search_soundcloud(content, 30)
    if not results:
        return await msg.edit_text("😔 موردی یافت نشد.")

    total_pages = (len(results) - 1) // 10 + 1
    text_res = get_search_text(results[:10], 1, total_pages)
    
    buttons = []
    if total_pages > 1:
        buttons.append([("➡️ بعدی", f"page:{content}:1")])
        
    await msg.edit_text(text_res, reply_markup=InlineKeyboard(buttons) if buttons else None)


# =================== هندلر دکمه‌های شیشه‌ای ==================
@bot.on_callback_query()
async def handle_callback(client, callback_query):
    global BOT_USERNAME
    if not BOT_USERNAME: 
        BOT_USERNAME = (await client.get_me()).username
    
    data = callback_query.data

    # دکمه‌های صفحه‌بندی
    if data.startswith("page:"):
        parts = data.split(":", 2)
        if len(parts) != 3: return
        _, keyword, page_index = parts
        page_index = int(page_index)
        
        results = await search_soundcloud(keyword, 30)
        total_pages = (len(results) - 1) // 10 + 1
        start = page_index * 10
        end = start + 10
        
        text_res = get_search_text(results[start:end], page_index + 1, total_pages)
        
        nav_buttons = []
        if page_index > 0: 
            nav_buttons.append(("⬅️ قبلی", f"page:{keyword}:{page_index - 1}"))
        if end < len(results): 
            nav_buttons.append(("➡️ بعدی", f"page:{keyword}:{page_index + 1}"))
        
        keyboard = InlineKeyboard([nav_buttons]) if nav_buttons else None
        await callback_query.message.edit_text(text_res, reply_markup=keyboard)

    # دانلود و ارسال فایل صوتی
    elif data.startswith("getaudio:"):       
        parts = data.split(":")
        if len(parts) < 2: return
        track_id = parts[1]
        
        await callback_query.answer("⏳ در حال پردازش فایل، لطفا صبور باشید...")
        
        # جستجوی امن در دیتابیس
        row = db.run_query("SELECT * FROM tracks WHERE uuid=?", (f"sc_{track_id}",), fetchone=True)
        if not row:
            return await callback_query.message.reply("❌ اطلاعات این آهنگ منقضی شده است. لطفا دوباره لینک را بفرستید.")

        caption = build_caption(row, BOT_USERNAME)
        msg_to_delete = callback_query.message
        url = row.get("webpage_url")

        # اگر از قبل در کانال کش ذخیره شده باشد
        if row.get("cache_msg_id"):
            try:
                await client.send_audio(callback_query.message.chat.id, row["cache_msg_id"], caption=caption)
                await msg_to_delete.delete()
                return
            except Exception:
                pass # در صورت نامعتبر بودن کش، به دانلود ادامه می‌دهیم

        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            return await callback_query.message.reply(f"❌ خطا در دانلود: {e}")

        try:
            with open(filepath, "rb") as f:
                sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f, caption=caption)
            
            # پیدا کردن ID فایل آپلود شده
            file_id = None
            if hasattr(sent_msg, 'audio') and sent_msg.audio:
                file_id = sent_msg.audio.id
            elif hasattr(sent_msg, 'document') and sent_msg.document:
                file_id = sent_msg.document.id
                
            if file_id:
                row["cache_msg_id"] = str(file_id)
                placeholders = ','.join(['?'] * len(row))
                db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(row.keys())}) VALUES ({placeholders})", tuple(row.values()))
            
            await client.send_audio(callback_query.message.chat.id, file_id if file_id else filepath, caption=caption)
            await msg_to_delete.delete()
            
        except Exception as e:
            await callback_query.message.reply(f"❌ خطا در آپلود (ممکن است فایل خیلی بزرگ باشد): {e}")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

if __name__ == "__main__":
    bot.run()
