import os
import sqlite3
import yt_dlp
import re
import glob
from balethon import Client
from balethon.conditions import private, command
from balethon.objects import Message, CallbackQuery, InlineKeyboard, InlineKeyboardButton

# دریافت متغیرهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN")
archive_id_env = os.getenv("DB_CHANNEL_ID")
ARCHIVE_CHANNEL_ID = int(archive_id_env) if archive_id_env else 0

app = Client(BOT_TOKEN)

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
    """پاک کردن تمام فایل‌های موقت مربوط به یک آیدی"""
    for file in glob.glob(f"{yt_id}.*"):
        try:
            os.remove(file)
        except OSError:
            pass

# ================= هندلرهای ربات =================

@app.on_message(private & command("start"))
async def start_command(message: Message):
    welcome_text = (
        "👋 سلام! به ربات جستجو و دانلود از یوتیوب خوش آمدید.\n\n"
        "برای شروع، می‌توانید:\n"
        "۱. نام آهنگ یا خواننده مورد نظر خود را تایپ کنید تا جستجو کنم.\n"
        "۲. لینک مستقیم یک ویدیو از یوتیوب را بفرستید.\n\n"
        "⚙️ امکانات: تبدیل خودکار به mp3، اضافه کردن کاور و متادیتا، و آرشیو فایل‌ها."
    )
    await message.reply(welcome_text)

@app.on_message(private)
async def handle_message(message: Message):
    text = message.text
    if not text or text.startswith('/'):
        return
        
    # تشخیص لینک یوتیوب
    if re.match(r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$', text):
        await send_track_info(message, text)
    else:
        # جستجو در یوتیوب
        wait_msg = await message.reply("🔍 در حال جستجو در یوتیوب...")
        try:
            info = extract_info(f"ytsearch5:{text}", is_search=True)
            if not info or 'entries' not in info or not info['entries']:
                await wait_msg.edit_text("❌ نتیجه‌ای یافت نشد. لطفاً عبارت دیگری را امتحان کنید.")
                return

            keyboard = []
            for entry in info['entries']:
                btn_text = f"🎵 {entry.get('title', 'Unknown')} ({entry.get('duration_string', '?')})"
                callback_data = f"info|{entry['id']}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data)])
            
            await wait_msg.edit_text("✅ نتایج یافت شده:", reply_markup=InlineKeyboard(*keyboard))
        except Exception as e:
            await wait_msg.edit_text(f"❌ خطا در جستجو: {str(e)}")

async def send_track_info(message_or_query, query_or_id):
    chat_id = message_or_query.message.chat.id if isinstance(message_or_query, CallbackQuery) else message_or_query.chat.id
    
    if isinstance(message_or_query, CallbackQuery):
        await message_or_query.answer("در حال دریافت اطلاعات...")
        msg_to_edit = message_or_query.message
    else:
        msg_to_edit = await message_or_query.reply("⏳ در حال استخراج اطلاعات...")

    try:
        info = extract_info(query_or_id)
        yt_id = info['id']
        title = info.get('title', 'Unknown Title')
        artist = info.get('uploader', info.get('artist', 'Unknown Artist'))
        thumb = info.get('thumbnail', '')
        
        caption = f"🎵 **عنوان:** {title}\n👤 **آرتیست:** {artist}\n\nبرای دانلود روی دکمه زیر کلیک کنید:"
        keyboard = InlineKeyboard([InlineKeyboardButton("⬇️ دانلود (MP3)", f"dl|{yt_id}")])

        if isinstance(message_or_query, Message):
            await msg_to_edit.delete()

        if thumb:
            await app.send_photo(chat_id, photo=thumb, caption=caption, reply_markup=keyboard)
        else:
            await app.send_message(chat_id, text=caption, reply_markup=keyboard)
            
    except Exception as e:
        if isinstance(message_or_query, Message):
            await msg_to_edit.edit_text(f"❌ خطا در دریافت اطلاعات: {str(e)}")
        else:
            await app.send_message(chat_id, f"❌ خطا: {str(e)}")

@app.on_callback_query()
async def handle_callback(query: CallbackQuery):
    data = query.data
    action, yt_id = data.split('|')
    chat_id = query.message.chat.id
    
    if action == "info":
        await send_track_info(query, yt_id)
        
    elif action == "dl":
        await query.answer("بررسی درخواست...")
        
        # ۱. بررسی دیتابیس
        db_result = get_track_from_db(yt_id)
        if db_result and db_result[0]:
            msg = await app.send_message(chat_id, "✅ این آهنگ در آرشیو موجود است! در حال ارسال...")
            await app.copy_message(chat_id=chat_id, from_chat_id=ARCHIVE_CHANNEL_ID, message_id=db_result[0])
            await msg.delete()
            return

        # ۲. دانلود فایل
        status_msg = await app.send_message(chat_id, "⏳ در حال دانلود و تبدیل به MP3 با کیفیت بالا (لطفا صبور باشید)...")
        
        dl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(id)s.%(ext)s',
            'cookiefile': 'cookies.txt',
            'quiet': True,
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
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
                    await status_msg.edit_text("✅ دانلود کامل شد. در حال آپلود...")
                    
                    # ارسال به کانال آرشیو
                    archive_msg = await app.send_document(
                        chat_id=ARCHIVE_CHANNEL_ID,
                        document=filename,
                        caption=f"🎵 Title: {title}\n👤 Artist: {artist}\n🆔 ID: {yt_id}"
                    )
                    
                    # ذخیره در دیتابیس
                    save_track_to_db(yt_id, title, artist, archive_msg.id)
                    
                    # ارسال به کاربر
                    await app.send_document(chat_id=chat_id, document=filename, caption=title)
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ خطا: فایل نهایی یافت نشد (احتمالاً تبدیل با مشکل مواجه شده است).")

        except Exception as e:
            await status_msg.edit_text(f"❌ خطا در دانلود: {str(e)}")
        finally:
            # پاک‌سازی فایل‌های موقت
            cleanup_files(yt_id)

if __name__ == "__main__":
    app.run()
