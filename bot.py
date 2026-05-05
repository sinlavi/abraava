import asyncio
import os
import re
import sqlite3
from pathlib import Path
import aiohttp
from mutagen import File
import yt_dlp
from balethon import Client
from balethon.conditions import private, command, text
from balethon.objects import InlineKeyboard

# ===================== تنظیمات =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BALE_BOT_TOKEN")
CACHE_CHANNEL_ID = int(os.getenv("CACHE_CHANNEL_ID", "-1000000000000"))

TEMP_DIR = Path("temp_soundcloud")
TEMP_DIR.mkdir(exist_ok=True)
DB_PATH = "cache.db"

bot = Client(BOT_TOKEN)
BOT_USERNAME = ""  # مقدار در start هندلر گرفته می‌شود


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
            # بررسی اینکه ستون‌ها کامل هستند؛ اگر حذف یا متفاوت باشند جدول را بازسازی کن
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
    title = track.get("title") or "نامشخص"
    artist = track.get("artist") or "نامشخص"
    caption = (
        f"🎧 *{title}*\n"
        f"🎤 هنرمند: *{artist}*\n"
        f"📅 سال: {track.get('year', '-')}\n"
        f"🎸 ژانر: {track.get('genre', '-')}\n"
        f"⏱ مدت: {track.get('duration', '-')}\n"
        f"🔗 [لینک اصلی]({track.get('webpage_url', '')})\n\n"
        "🤖 @abraava_bot"
    )
    return caption


def download_soundcloud_track(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        return filepath, info


# =================== هندلر start ==================
@bot.on_message(private & command("start"))
async def start_handler(client, message):
    global BOT_USERNAME
    me = await client.get_me()
    BOT_USERNAME = me.username
    txt = (
        "🎶 به ربات دانلودر ساندکلاود خوش آمدید!\n\n"
        "ارسال کنید:\n"
        "🔗 یک لینک ساندکلاود — تا آهنگ را با کاور و جزئیات کامل دریافت کنید.\n"
        "🕵️ متن جستجو — تا نتایج آلبوم‌ها و ترک‌ها را ببینید.\n\n"
        "📌 نتیجه‌ها با دکمهٔ دریافت همراه‌اند و فایل‌ها در کانال آرشیو ذخیره می‌شوند."
    )
    await message.reply(txt)


# =================== هندلر لینک ساندکلاود ==================
@bot.on_message(private & text)
async def handle_text(client, message):
    content = message.text.strip()

    # اگر لینک ساندکلاود است
    if "soundcloud.com" in content:
        await message.reply("⏳ بررسی لینک و دریافت اطلاعات...")
        url = re.search(r"(https?://[^\s]+)", content)
        if not url:
            return await message.reply("❌ لینک نامعتبر!")
        url = url.group(1)

        # بررسی در دیتابیس
        existing = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if existing and existing.get("cache_msg_id"):
            # ارسال فایل موجود
            caption = build_caption(existing)
            return await client.send_document(message.chat.id, existing["cache_msg_id"], caption=caption)

        # دریافت و ذخیره
        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            return await message.reply(f"❌ خطا در ساندکلاود: {e}")

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
        photo_url = meta["thumbnail"]
        sent_msg = await client.send_audio(CACHE_CHANNEL_ID, filepath, caption=caption)
        meta["cache_msg_id"] = sent_msg.audio.id

        db.run_query(
            f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({','.join(['?'] * len(meta))})",
            tuple(meta.values())
        )

        if photo_url:
            await client.send_photo(message.chat.id, photo_url, caption=caption)
        else:
            await message.reply(caption)

        await message.reply("✅ آهنگ ذخیره و آماده‌ی پخش شد!")

        # پاک کردن فایل دانلودی
        if os.path.exists(filepath):
            os.remove(filepath)
        return

    # اگر متن جستجو است (Search)
    if not content.startswith("/"):
        await message.reply("🔍 در حال جستجو در ساندکلاود...")
        results = await search_soundcloud(content)
        if not results:
            return await message.reply("😔 موردی یافت نشد.")

        # صفحه اول
        buttons = []
        for item in results[:5]:
            buttons.append([(f"🎧 {item['title']} - {item['artist'][:15]}", f"show:{item['webpage_url']}")])
        if len(results) > 5:
            buttons.append([("➡️ بعدی", f"page:{content}:1")])

        await message.reply(f"🎯 نتایج برای **{content}**", InlineKeyboard(*buttons))


# =================== توابع جستجو و صفحه‌بندی ==================
async def search_soundcloud(query):
    """استفاده از yt_dlp برای جستجوی ساندکلاود"""
    results = []
    ydl_opts = {"quiet": True, "extract_flat": True, "default_search": f"scsearch5:{query}"}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"scsearch5:{query}", download=False)
        for e in info.get("entries", []):
            results.append({
                "title": e.get("title", ""),
                "uploader": e.get("uploader", ""),
                "webpage_url": e.get("url", ""),
            })
    return results


@bot.on_callback_query()
async def handle_callback(client, callback_query):
    data = callback_query.data
    if data.startswith("page:"):
        _, keyword, page_index = data.split(":")
        page_index = int(page_index)
        results = await search_soundcloud(keyword)
        start = page_index * 5
        end = start + 5
        buttons = []
        for item in results[start:end]:
            buttons.append([(f"🎧 {item['title']} - {item['artist'][:15]}", f"show:{item['webpage_url']}")])
        if end < len(results):
            buttons.append([("➡️ بعدی", f"page:{keyword}:{page_index + 1}")])
        if start > 0:
            buttons.append([("⬅️ قبلی", f"page:{keyword}:{page_index - 1}")])
        await callback_query.message.edit_text(f"🎯 نتایج برای **{keyword}** (صفحه {page_index + 1})",
                                               InlineKeyboard(*buttons))

    elif data.startswith("show:"):
        url = data.split(":", 1)[1]
        # بررسی و ارسال جزئیات آهنگ
        row = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if row:
            caption = build_caption(row)
            if row.get("thumbnail"):
                await client.send_photo(callback_query.message.chat.id, row["thumbnail"], caption=caption,
                                        reply_markup=InlineKeyboard([("⬇️ دریافت", f"dl:{url}")]))
            else:
                await callback_query.message.reply(caption, InlineKeyboard([("⬇️ دریافت", f"dl:{url}")]))
            return

        await callback_query.message.reply("⏳ دریافت اطلاعات از ساندکلاود...")
        loop = asyncio.get_event_loop()
        try:
            _, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            return await callback_query.message.reply(f"خطا در دریافت اطلاعات: {e}")

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
        db.run_query(
            f"INSERT OR REPLACE INTO tracks ({','.join(meta.keys())}) VALUES ({','.join(['?'] * len(meta))})",
            tuple(meta.values())
        )
        caption = build_caption(meta)
        await bot.send_photo(callback_query.message.chat.id, meta["thumbnail"], caption=caption,
                             reply_markup=InlineKeyboard([("⬇️ دریافت", f"dl:{url}")]))

    elif data.startswith("dl:"):
        url = data.split(":", 1)[1]
        row = db.run_query("SELECT * FROM tracks WHERE webpage_url=?", (url,), fetchone=True)
        if row and row.get("cache_msg_id"):
            return await client.send_document(callback_query.message.chat.id, row["cache_msg_id"],
                                              caption=build_caption(row))

        await callback_query.message.reply("⬇️ در حال دریافت از ساندکلاود...")
        loop = asyncio.get_event_loop()
        try:
            filepath, info = await loop.run_in_executor(None, download_soundcloud_track, url)
        except Exception as e:
            return await callback_query.message.reply(f"❌ خطا در دریافت: {e}")

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
        sent_msg = await client.send_audio(CACHE_CHANNEL_ID, filepath, caption=caption)
        db.run_query("UPDATE tracks SET cache_msg_id=? WHERE webpage_url=?", (sent_msg.audio.id, url))
        await client.send_audio(callback_query.message.chat.id, filepath, caption=caption)
        if os.path.exists(filepath):
            os.remove(filepath)


# =================== اجرا =====================
if __name__ == "__main__":
    bot.run()
