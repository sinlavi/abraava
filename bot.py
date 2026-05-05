import asyncio
import os
import re
import sqlite3
from pathlib import Path
import yt_dlp
from balethon import Client
from balethon.conditions import private, command, text
from balethon.objects import InlineKeyboard, InlineQueryResultArticle, InputTextMessageContent

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
                return dict(c.fetchone() or {})
            if fetch:
                return [dict(r) for r in c.fetchall()]
            conn.commit()

db = DatabaseManager(DB_PATH)


def build_caption(track):
    return (
        f"🎧 *{track.get('title','نامشخص')}*\n"
        f"🎤 هنرمند: *{track.get('uploader','نامشخص')}*\n"
        f"📅 سال: {track.get('upload_date','نامشخص')}\n"
        f"🎸 ژانر: {track.get('genre','نامشخص')}\n"
        f"⏱ مدت: {track.get('duration','نامشخص')}\n"
        f"🔗 [لینک اصلی]({track.get('webpage_url','نامشخص')})\n\n"
        f"🤖 @{BOT_USERNAME}"
    )


# =================== توابع ساندکلاود ==================
def get_soundcloud_info(url):
    """فقط دریافت اطلاعات بدون دانلود"""
    ydl_opts = {"quiet": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info

def download_soundcloud_track(url):
    """دانلود با تبدیل اجباری به MP3 برای جلوگیری از خطای 500 بله"""
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
        # مسیر فایل نهایی mp3 را دریافت می‌کنیم
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
                "webpage_url": e.get("url", ""),
                "thumbnail": e.get("thumbnail", "") # ممکن است خالی باشد
            })
    return results


# =================== هندلر start ==================
@bot.on_message(private & command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    me = await client.get_me()
    BOT_USERNAME = me.username
    txt = (
        "🎶 به ربات دانلودر ساندکلاود خوش آمدید!\n\n"
        "🔗 ارسال لینک: آهنگ را با کاور و جزئیات دریافت کنید.\n"
        "🕵️ ارسال متن: جستجوی آلبوم‌ها و ترک‌ها.\n"
        f"✨ *جدید:* می‌توانید در هر گروهی از طریق `@ {BOT_USERNAME} نام‌اهنگ` جستجو کنید!"
    )
    await message.reply(txt)


# =================== هندلر لینک و جستجوی متنی ==================
@bot.on_message(private & text)
async def handle_text(client, message):
    content = message.text.strip()

    # اگر لینک ساندکلاود است
    if "soundcloud.com" in content:
        url_match = re.search(r"(https?://[^\s]+)", content)
        if not url_match:
            return await message.reply("❌ لینک نامعتبر!")
        url = url_match.group(1)

        # 1. بررسی در کش
        row = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if row and row.get("cache_msg_id"):
            return await client.send_document(message.chat.id, row["cache_msg_id"], caption=build_caption(row))

        msg = await message.reply("⏳ در حال دانلود و آماده‌سازی...")
        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            return await msg.edit_text(f"❌ خطا: {e}")

        meta = {
            "uuid": f"sc_{info['id']}",
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "genre": info.get("genre", ""),
            "upload_date": str(info.get("upload_date", ""))[:4],
            "webpage_url": info.get("webpage_url", url),
            "thumbnail": info.get("thumbnail", ""),
            "duration": str(info.get("duration", "")),
        }
        caption = build_caption(meta)

        with open(filepath, "rb") as f:
            sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f, caption=caption)
        
        meta["cache_msg_id"] = str(sent_msg.audio.id)
        db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({','.join(['?'] * len(meta))})", tuple(meta.values()))

        # ارسال به کاربر
        await client.send_audio(message.chat.id, sent_msg.audio.id, caption=caption)
        await msg.delete()

        if os.path.exists(filepath):
            os.remove(filepath)
        return

    # اگر جستجو است
    if not content.startswith("/"):
        msg = await message.reply("🔍 در حال جستجو...")
        results = await search_soundcloud(content, 15)
        if not results:
            return await msg.edit_text("😔 موردی یافت نشد.")

        buttons = [[(f"🎧 {item['title'][:20]}", f"show:{item['webpage_url']}")] for item in results[:10]]
        if len(results) > 10:
            buttons.append([("➡️ بعدی", f"page:{content}:1")])
        await msg.edit_text(f"🎯 نتایج برای *{content}*", InlineKeyboard(*buttons))


# =================== اینلاین کوئری (جستجو در گروه‌ها) ==================
@bot.on_inline_query()
async def inline_search(client, inline_query):
    query = inline_query.query.strip()
    if not query:
        return

    results = await search_soundcloud(query, max_results=10)
    articles = []
    
    for item in results:
        caption = f"🎵 *{item['title']}*\n🎤 {item['uploader']}"
        articles.append(
            InlineQueryResultArticle(
                id=item["id"],
                title=item["title"],
                description=item["uploader"],
                thumb_url=item["thumbnail"] if item.get("thumbnail") else None,
                input_message_content=InputTextMessageContent(
                    f"{caption}\n\n[لینک ساندکلاود]({item['webpage_url']})"
                ),
                reply_markup=InlineKeyboard(
                    [("⬇️ دریافت این آهنگ در ربات", f"dl:{item['webpage_url']}")]
                )
            )
        )
    await inline_query.answer(articles, cache_time=300)


# =================== هندلر دکمه‌های شیشه‌ای ==================
@bot.on_callback_query()
async def handle_callback(client, callback_query):
    data = callback_query.data

    if data.startswith("page:"):
        _, keyword, page_index = data.split(":")
        page_index = int(page_index)
        results = await search_soundcloud(keyword, 30)
        start = page_index * 10
        end = start + 10
        buttons = [[(f"🎧 {item['title'][:20]}", f"show:{item['webpage_url']}")] for item in results[start:end]]
        nav_buttons = []
        if start > 0: nav_buttons.append(("⬅️ قبلی", f"page:{keyword}:{page_index - 1}"))
        if end < len(results): nav_buttons.append(("➡️ بعدی", f"page:{keyword}:{page_index + 1}"))
        if nav_buttons: buttons.append(nav_buttons)
        await callback_query.message.edit_text(f"🎯 نتایج برای *{keyword}* (صفحه {page_index + 1})", InlineKeyboard(*buttons))

    elif data.startswith("show:"):
        url = data.split(":", 1)[1]
        
        row = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if row:
            return await callback_query.message.reply(build_caption(row), InlineKeyboard([("⬇️ دریافت", f"dl:{url}")]))

        msg = await callback_query.message.reply("⏳ دریافت اطلاعات...")
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, get_soundcloud_info, url)
        except Exception as e:
            return await msg.edit_text(f"خطا: {e}")

        meta = {
            "uuid": f"sc_{info['id']}",
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "genre": info.get("genre", ""),
            "upload_date": str(info.get("upload_date", ""))[:4],
            "webpage_url": info.get("webpage_url", url),
            "thumbnail": info.get("thumbnail", ""),
            "duration": str(info.get("duration", "")),
        }
        db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({','.join(['?'] * len(meta))})", tuple(meta.values()))
        await msg.edit_text(build_caption(meta), InlineKeyboard([("⬇️ دریافت", f"dl:{url}")]))

    elif data.startswith("dl:"):
        url = data.split(":", 1)[1]
        
        # در صورتی که دکمه از طریق حالت اینلاین زده شده باشد و ربات پیامی نداشته باشد
        try:
            msg = await callback_query.message.reply("⬇️ در حال پردازش فایل...")
        except:
            msg = None # پیام‌های ویا ربات قابل ریپلای نیستند مستقیماً در گروه مگر اینکه ربات ادمین باشد

        row = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if row and row.get("cache_msg_id"):
            await client.send_document(callback_query.message.chat.id, row["cache_msg_id"], caption=build_caption(row))
            if msg: await msg.delete()
            return

        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            if msg: await msg.edit_text(f"❌ خطا: {e}")
            return

        meta = {
            "uuid": f"sc_{info['id']}",
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "genre": info.get("genre", ""),
            "upload_date": str(info.get("upload_date", ""))[:4],
            "webpage_url": info.get("webpage_url", url),
            "thumbnail": info.get("thumbnail", ""),
            "duration": str(info.get("duration", "")),
        }
        caption = build_caption(meta)

        with open(filepath, "rb") as f:
            sent_msg = await client.send_audio(CACHE_CHANNEL_ID, f, caption=caption)
            
        meta["cache_msg_id"] = str(sent_msg.audio.id)
        db.run_query(f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({','.join(['?'] * len(meta))})", tuple(meta.values()))
        
        await client.send_audio(callback_query.message.chat.id, sent_msg.audio.id, caption=caption)
        if msg: await msg.delete()
        
        if os.path.exists(filepath):
            os.remove(filepath)

# =================== اجرا =====================
if __name__ == "__main__":
    bot.run()
