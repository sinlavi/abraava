import os
import sqlite3
import yt_dlp
import re
import glob
import uuid
from balethon import Client
from balethon.conditions import private, command
from balethon.objects import Message, CallbackQuery, InlineKeyboard, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN")
archive_id_env = os.getenv("DB_CHANNEL_ID")
ARCHIVE_CHANNEL_ID = int(archive_id_env) if archive_id_env else 0

app = Client(BOT_TOKEN)

SEARCH_CACHE = {}
PAGE_SIZE = 5

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect('archive.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            yt_id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            message_id INTEGER
        )
    ''')
    conn.commit()
    return conn

db_conn = init_db()

def get_track_from_db(yt_id):
    cursor = db_conn.cursor()
    cursor.execute('SELECT message_id, title, artist FROM tracks WHERE yt_id = ?', (yt_id,))
    return cursor.fetchone()

def save_track_to_db(yt_id, title, artist, message_id):
    cursor = db_conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO tracks (yt_id, title, artist, message_id) VALUES (?, ?, ?, ?)',
        (yt_id, title, artist, message_id)
    )
    db_conn.commit()

# ================= YTDLP =================

base_ydl_opts = {
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'noplaylist': True,
}

def extract_info(query, is_search=False):
    opts = base_ydl_opts.copy()

    if is_search:
        opts.update({
            'extract_flat': True
        })

    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(query, download=False)

def cleanup_files(yt_id):
    for file in glob.glob(f"{yt_id}.*"):
        try:
            os.remove(file)
        except:
            pass

def extract_video_id(url):
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return url

# ================= HELPERS =================

def get_artist(info):
    if info.get("artist"):
        return info["artist"]

    if info.get("artists"):
        return ", ".join([a.get("name") for a in info["artists"] if a.get("name")])

    if info.get("channel"):
        return info["channel"]

    if info.get("uploader"):
        return info["uploader"]

    return "Unknown Artist"


def get_pagination_keyboard(search_id, page):
    entries = SEARCH_CACHE.get(search_id, [])

    total_pages = (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    current_entries = entries[start:end]

    keyboard = []

    for entry in current_entries:
        title = entry.get("title", "Unknown")
        duration = entry.get("duration_string", "?")
        vid = entry.get("id")

        keyboard.append([
            InlineKeyboardButton(
                f"🎵 {title} ({duration})",
                f"info|{vid}"
            )
        ])

    nav = []

    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", f"page|{search_id}|{page-1}"))

    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ➡️", f"page|{search_id}|{page+1}"))

    if nav:
        keyboard.append(nav)

    return InlineKeyboard(*keyboard)

# ================= BOT =================

@app.on_message(private & command("start"))
async def start_command(client: Client, message: Message):
    await message.reply(
        "👋 سلام\n\n"
        "نام آهنگ یا لینک YouTube Music بفرست."
    )


@app.on_message(private)
async def handle_message(client: Client, message: Message):

    text = message.text
    if not text or text.startswith("/"):
        return

    # لینک یوتیوب
    if re.match(r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$', text):
        await send_track_info(client, message, text)
        return

    wait = await message.reply("🔍 جستجو در YouTube Music ...")

    try:

        # سرچ در یوتیوب موزیک
        info = extract_info(f"ytmsearch20:{text}", is_search=True)

        if not info or not info.get("entries"):
            await wait.edit_text("❌ نتیجه‌ای پیدا نشد")
            return

        search_id = str(uuid.uuid4())[:8]

        SEARCH_CACHE[search_id] = info["entries"]

        keyboard = get_pagination_keyboard(search_id, 0)

        await wait.edit_text(
            "✅ نتایج:",
            reply_markup=keyboard
        )

    except Exception as e:
        await wait.edit_text(f"❌ خطا\n{e}")


async def send_track_info(client, message_or_query, query_or_id):
    chat_id = message_or_query.message.chat.id if isinstance(message_or_query, CallbackQuery) else message_or_query.chat.id

    if isinstance(message_or_query, CallbackQuery):
        msg = message_or_query.message
    else:
        msg = await message_or_query.reply("⏳ دریافت اطلاعات...")

    yt_id = extract_video_id(query_or_id)

    db = get_track_from_db(yt_id)

    if db:
        message_id, title, artist = db
        thumb = None
        cached = True
    else:

        try:

            info = extract_info(yt_id)

            yt_id = info["id"]

            title = info.get("title", "Unknown")

            artist = get_artist(info)

            thumb = info.get("thumbnail")

            cached = False

        except Exception as e:
            await client.send_message(chat_id, f"❌ خطا\n{e}")
            return

    caption = f"🎵 {title}\n👤 {artist}\n"

    if cached:
        caption += "\n💾 در آرشیو موجود است"

    keyboard = InlineKeyboard([
        InlineKeyboardButton(
            "⬇️ دانلود MP3",
            f"dl|{yt_id}"
        )
    ])

    if thumb and not cached:
        await client.send_photo(chat_id, thumb, caption=caption, reply_markup=keyboard)
    else:
        await client.send_message(chat_id, caption, reply_markup=keyboard)


@app.on_callback_query()
async def handle_callback(client, callback_query: CallbackQuery):

    data = callback_query.data
    chat_id = callback_query.message.chat.id

    action, *args = data.split("|")

    if action == "page":

        search_id = args[0]
        page = int(args[1])

        keyboard = get_pagination_keyboard(search_id, page)

        await callback_query.message.edit_reply_markup(keyboard)

        await callback_query.answer('')

    elif action == "info":

        await callback_query.answer('')

        await send_track_info(client, callback_query, args[0])

    elif action == "dl":

        yt_id = args[0]

        await callback_query.answer("در حال بررسی")

        db = get_track_from_db(yt_id)

        if db and db[0]:

            await client.copy_message(
                chat_id,
                ARCHIVE_CHANNEL_ID,
                db[0]
            )

            return

        status = await client.send_message(chat_id, "⏳ دانلود...")

        dl_opts ={
            'cookiefile': 'cookies.txt', # <--- این خط اضافه شود
            'format': 'ba/b',           
            'outtmpl': '%(id)s.%(ext)s',
            'noplaylist': True,
            'quiet': False,
            'concurrent_fragment_downloads': 1,
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 20,
            'sleep_interval': 5,
            'max_sleep_interval': 12,
            'sleep_interval_requests': 3,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192'
            },
                {
                    'key': 'FFmpegMetadata'
                }
            ]
        }

        try:

            with yt_dlp.YoutubeDL(dl_opts) as ydl:

                info = ydl.extract_info(yt_id, download=True)

                title = info.get("title")

                artist = get_artist(info)

                filename = f"{yt_id}.mp3"

                if os.path.exists(filename):

                    archive_msg = await client.send_document(
                        ARCHIVE_CHANNEL_ID,
                        filename,
                        caption=f"{title}\n{artist}\n{yt_id}"
                    )

                    save_track_to_db(yt_id, title, artist, archive_msg.id)

                    await client.send_document(chat_id, filename, caption=title)

                    await status.delete()

        except Exception as e:

            await status.edit_text(f"❌ خطا\n{e}")

        finally:

            cleanup_files(yt_id)


if __name__ == "__main__":
    app.run()
