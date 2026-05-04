import os
import sqlite3
import yt_dlp
import re
import glob
import uuid
from balethon import Client
from balethon.conditions import private, command
from balethon.objects import Message, CallbackQuery, InlineKeyboard, InlineKeyboardButton

# دریافت متغیرهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN")
archive_id_env = os.getenv("DB_CHANNEL_ID")
ARCHIVE_CHANNEL_ID = int(archive_id_env) if archive_id_env else 0

app = Client(BOT_TOKEN)

# کش موقت برای جستجوها (جهت صفحه‌بندی)
SEARCH_CACHE = {}
PAGE_SIZE = 5

# ================= دیتابیس =================
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
    cursor.execute('INSERT OR REPLACE INTO tracks (yt_id, title, artist, message_id) VALUES (?, ?, ?, ?)', 
                   (yt_id, title, artist, message_id))
    db_conn.commit()

# ================= تنظیمات yt-dlp =================
base_ydl_opts = {
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'noplaylist': True
}

def extract_info(query, is_search=False):
    opts = base_ydl_opts.copy()
    if is_search:
        opts['extract_flat'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(query, download=False)

def cleanup_files(yt_id):
    for file in glob.glob(f"{yt_id}.*"):
        try:
            os.remove(file)
        except OSError:
            pass

def extract_video_id(url):
    """استخراج شناسه ویدیو از لینک یوتیوب"""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return url

# ================= توابع کمکی =================

def get_pagination_keyboard(search_id, page):
    entries = SEARCH_CACHE.get(search_id, [])
    total_pages = (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE
    
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    current_entries = entries[start_idx:end_idx]
    
    keyboard = []
    for entry in current_entries:
        btn_text = f"🎵 {entry.get('title', 'Unknown')} ({entry.get('duration_string', '?')})"
        callback_data = f"info|{entry['id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data)])
        
    # دکمه‌های ناوبری
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", f"page|{search_id}|{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("بعدی ➡️", f"page|{search_id}|{page+1}"))
        
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    return InlineKeyboard(*keyboard)

# ================= هندلرهای ربات =================

@app.on_message(private & command("start"))
async def start_command(client: Client, message: Message):
    welcome_text = (
        "👋 سلام! به ربات جستجو و دانلود از یوتیوب خوش آمدید.\n\n"
        "برای شروع، می‌توانید:\n"
        "۱. نام آهنگ یا خواننده مورد نظر خود را تایپ کنید تا جستجو کنم.\n"
        "۲. لینک مستقیم یک ویدیو از یوتیوب را بفرستید."
    )
    await message.reply(welcome_text)

@app.on_message(private)
async def handle_message(client: Client, message: Message):
    text = message.text
    if not text or text.startswith('/'):
        return
        
    if re.match(r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$', text):
        await send_track_info(client, message, text)
    else:
        wait_msg = await message.reply("🔍 در حال جستجو در یوتیوب...")
        try:
            # دریافت 20 نتیجه
            info = extract_info(f"ytsearch20:{text}", is_search=True)
            if not info or 'entries' not in info or not info['entries']:
                await wait_msg.edit_text("❌ نتیجه‌ای یافت نشد.")
                return

            search_id = str(uuid.uuid4())[:8]
            SEARCH_CACHE[search_id] = info['entries']
            
            keyboard = get_pagination_keyboard(search_id, 0)
            await wait_msg.edit_text("✅ نتایج یافت شده:", reply_markup=keyboard)
        except Exception as e:
            await wait_msg.edit_text(f"❌ خطا در جستجو: {str(e)}")

async def send_track_info(client: Client, message_or_query, query_or_id):
    chat_id = message_or_query.message.chat.id if isinstance(message_or_query, CallbackQuery) else message_or_query.chat.id
    
    if isinstance(message_or_query, CallbackQuery):
        msg_to_edit = message_or_query.message
    else:
        msg_to_edit = await message_or_query.reply("⏳ در حال بررسی اطلاعات...")

    yt_id = extract_video_id(query_or_id)
    
    # 1. بررسی وجود در دیتابیس
    db_result = get_track_from_db(yt_id)
    
    if db_result:
        message_id, title, artist = db_result
        thumb = None
        is_cached = True
    else:
        # 2. استخراج اطلاعات از یوتیوب در صورت عدم وجود در دیتابیس
        try:
            if isinstance(message_or_query, CallbackQuery):
                await msg_to_edit.edit_text("⏳ در حال دریافت متادیتا از یوتیوب...")
            
            info = extract_info(yt_id)
            yt_id = info['id']
            title = info.get('title', 'Unknown Title')
            artist = info.get('uploader', info.get('artist', 'Unknown Artist'))
            thumb = info.get('thumbnail', '')
            is_cached = False
        except Exception as e:
            if isinstance(message_or_query, Message):
                await msg_to_edit.edit_text(f"❌ خطا در دریافت اطلاعات: {str(e)}")
            else:
                await client.send_message(chat_id, f"❌ خطا: {str(e)}")
            return

    caption = f"🎵 **عنوان:** {title}\n👤 **آرتیست:** {artist}\n"
    if is_cached:
        caption += "💾 *(موجود در دیتابیس)*\n\nبرای دریافت فایل روی دکمه زیر کلیک کنید:"
    else:
        caption += "\nبرای دانلود روی دکمه زیر کلیک کنید:"
        
    keyboard = InlineKeyboard([InlineKeyboardButton("⬇️ دانلود (MP3)", f"dl|{yt_id}")])

    if isinstance(message_or_query, Message):
        await msg_to_edit.delete()

    if thumb and not is_cached:
        await client.send_photo(chat_id, photo=thumb, caption=caption, reply_markup=keyboard)
    else:
        # اگر عکس در دسترس نبود یا در حالت کش بودیم (برای جلوگیری از دانلود مجدد عکس)
        await client.send_message(chat_id, text=caption, reply_markup=keyboard)


@app.on_callback_query()
async def handle_callback(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    try:
        action, *args = data.split('|')
    except ValueError:
        return

    if action == "page":
        search_id, page_str = args
        page = int(page_str)
        if search_id in SEARCH_CACHE:
            keyboard = get_pagination_keyboard(search_id, page)
            await callback_query.message.edit_reply_markup(keyboard)
        await callback_query.answer()

    elif action == "info":
        await callback_query.answer()
        await send_track_info(client, callback_query, args[0])
        
    elif action == "dl":
        yt_id = args[0]
        await callback_query.answer("بررسی درخواست...")
        
        # بررسی وجود فایل در دیتابیس و کانال آرشیو
        db_result = get_track_from_db(yt_id)
        if db_result and db_result[0]:
            msg = await client.send_message(chat_id, "✅ این آهنگ در آرشیو موجود است! در حال ارسال سریع...")
            await client.copy_message(chat_id=chat_id, from_chat_id=ARCHIVE_CHANNEL_ID, message_id=db_result[0])
            await msg.delete()
            return

        status_msg = await client.send_message(chat_id, "⏳ در حال دانلود و تبدیل به MP3 با کیفیت بالا...")
        
        dl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(id)s.%(ext)s',
            'cookiefile': 'cookies.txt',
            'quiet': True,
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegExtractAudio'},
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata'},
            ],
        }

        try:
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                info = ydl.extract_info(yt_id, download=True)
                title = info.get('title', 'Unknown')
                artist = info.get('uploader', 'Unknown')
                filename = f"{yt_id}.mp3"
                
                if os.path.exists(filename):
                    await status_msg.edit_text("✅ دانلود کامل شد. در حال آپلود و ذخیره در آرشیو...")
                    
                    # ارسال به کانال آرشیو
                    archive_msg = await client.send_document(
                        chat_id=ARCHIVE_CHANNEL_ID,
                        document=filename,
                        caption=f"🎵 Title: {title}\n👤 Artist: {artist}\n🆔 ID: {yt_id}"
                    )
                    
                    # ذخیره اطلاعات و آیدی پیام در دیتابیس
                    save_track_to_db(yt_id, title, artist, archive_msg.id)
                    
                    # ارسال برای کاربر
                    await client.send_document(chat_id=chat_id, document=filename, caption=title)
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ خطا: فایل نهایی یافت نشد.")

        except Exception as e:
            await status_msg.edit_text(f"❌ خطا در دانلود: {str(e)}")
        finally:
            cleanup_files(yt_id)

if __name__ == "__main__":
    app.run()
