import os
import sqlite3
import yt_dlp
import re
import glob
from ytmusicapi import YTMusic
from balethon import Client
from balethon.conditions import private
from balethon.objects import Message, CallbackQuery, InlineKeyboard, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
ARCHIVE_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "0"))

app = Client(BOT_TOKEN)
ytmusic = YTMusic()

# ================= DATABASE & HELPERS =================
# (توابع دیتابیس init_db, get_track_from_db, save_track_to_db مشابه قبل اینجا قرار میگیرند)
def init_db():
    conn = sqlite3.connect('archive.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS tracks (yt_id TEXT PRIMARY KEY, title TEXT, artist TEXT, message_id INTEGER)')
    conn.commit()
    return conn

db_conn = init_db()

def get_track_from_db(yt_id):
    cursor = db_conn.cursor()
    cursor.execute('SELECT message_id, title, artist FROM tracks WHERE yt_id = ?', (yt_id,))
    return cursor.fetchone()

def save_track_to_db(yt_id, title, artist, message_id):
    cursor = db_conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO tracks (yt_id, title, artist, message_id) VALUES (?, ?, ?, ?)', (yt_id, title, artist, message_id))
    db_conn.commit()

def extract_video_id(url):
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', url)
    return match.group(1) if match else url

def cleanup_files(yt_id):
    for f in glob.glob(f"{yt_id}.*"):
        try: os.remove(f)
        except: pass

# ================= BOT HANDLERS =================

@app.on_message(private)
async def handle_message(client: Client, message: Message):
    text = message.text
    if not text or text.startswith("/"): return

    if re.match(r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$', text):
        await send_track_info(client, message, extract_video_id(text))
        return

    wait_msg = await message.reply("🔍 در حال جستجوی همزمان...")
    
    try:
        # جستجوی کلی بدون فیلتر
        results = ytmusic.search(text, limit=15)
        
        keyboard = []
        
        # دسته‌بندی نتایج
        for r in results:
            rtype = r.get('resultType')
            if rtype == 'artist':
                name = r.get('artist', 'Unknown')
                browse_id = r.get('browseId')
                if browse_id:
                    keyboard.append([InlineKeyboardButton(f"🎤 آرتیست: {name[:20]}", f"art|{browse_id}")])
            elif rtype == 'album':
                title = r.get('title', 'Unknown')
                browse_id = r.get('browseId')
                if browse_id:
                    keyboard.append([InlineKeyboardButton(f"💿 آلبوم: {title[:20]}", f"alb|{browse_id}")])
            elif rtype in ['song', 'video']:
                title = r.get('title', 'Unknown')
                vid = r.get('videoId')
                if vid:
                    keyboard.append([InlineKeyboardButton(f"🎵 ترک: {title[:20]}", f"trk|{vid}")])

        if not keyboard:
            await wait_msg.edit_text("❌ نتیجه‌ای یافت نشد.")
            return

        await wait_msg.edit_text(f"✅ نتایج جستجو برای: {text}", reply_markup=InlineKeyboard(*keyboard[:10])) # نمایش 10 نتیجه برتر
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا: {e}")

async def send_track_info(client, context, vid):
    chat_id = context.message.chat.id if isinstance(context, CallbackQuery) else context.chat.id
    
    # دریافت اطلاعات سریع از ytmusicapi بجای ytdlp برای نمایش سریعتر
    try:
        track_info = ytmusic.get_song(vid)
        vid_details = track_info.get('videoDetails', {})
        title = vid_details.get('title', 'Unknown')
        artist = vid_details.get('author', 'Unknown')
        thumb = vid_details.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url')
    except:
        title, artist, thumb = "Unknown", "Unknown", None

    db = get_track_from_db(vid)
    caption = f"🎵 {title}\n👤 {artist}"
    if db: caption += "\n\n💾 موجود در آرشیو"

    keyboard = InlineKeyboard([
        InlineKeyboardButton("⬇️ دانلود MP3", f"dl|{vid}"),
        InlineKeyboardButton("🔙 بازگشت / بستن", "close")
    ])

    if isinstance(context, CallbackQuery):
        if thumb:
            await client.send_photo(chat_id, thumb, caption=caption, reply_markup=keyboard)
        else:
            await context.message.reply(caption, reply_markup=keyboard)
    else:
        if thumb:
            await client.send_photo(chat_id, thumb, caption=caption, reply_markup=keyboard)
        else:
            await context.reply(caption, reply_markup=keyboard)

@app.on_callback_query()
async def handle_callback(client: Client, query: CallbackQuery):
    data = query.data
    chat_id = query.message.chat.id
    action, *args = data.split("|")

    try:
        if action == "art":
            browse_id = args[0]
            artist = ytmusic.get_artist(browse_id)
            name = artist.get('name', 'Unknown')
            desc = artist.get('description', '')[:100] + "..."
            
            keyboard = []
            # نمایش برترین آهنگ‌های آرتیست
            if 'songs' in artist and 'results' in artist['songs']:
                for song in artist['songs']['results'][:5]:
                    vid = song.get('videoId')
                    if vid: keyboard.append([InlineKeyboardButton(f"🎵 {song['title'][:25]}", f"trk|{vid}")])
            
            # نمایش آلبوم‌ها
            if 'albums' in artist and 'results' in artist['albums']:
                for alb in artist['albums']['results'][:5]:
                    aid = alb.get('browseId')
                    if aid: keyboard.append([InlineKeyboardButton(f"💿 {alb['title'][:25]}", f"alb|{aid}")])
            
            keyboard.append([InlineKeyboardButton("🔙 بستن", "close")])
            await query.message.reply(f"🎤 آرتیست: {name}\n\n{desc}", reply_markup=InlineKeyboard(*keyboard))
            await query.answer('')

        elif action == "alb":
            browse_id = args[0]
            album = ytmusic.get_album(browse_id)
            title = album.get('title', 'Unknown')
            artist = album.get('artists', [{'name': ''}])[0].get('name', '')
            
            keyboard = []
            for track in album.get('tracks', []):
                vid = track.get('videoId')
                if vid:
                    keyboard.append([InlineKeyboardButton(f"🎵 {track['title'][:30]}", f"trk|{vid}")])
                    
            keyboard.append([InlineKeyboardButton("🔙 بستن", "close")])
            await query.message.reply(f"💿 آلبوم: {title}\n👤 {artist}", reply_markup=InlineKeyboard(*keyboard))
            await query.answer('')

        elif action == "trk":
            await query.answer('')
            await send_track_info(client, query, args[0])

        elif action == "close":
            await query.message.delete()
            await query.answer('')

        elif action == "dl":
            yt_id = args[0]
            await query.answer("در حال آماده‌سازی...")
            
            db = get_track_from_db(yt_id)
            if db and db[0]:
                await client.copy_message(chat_id, ARCHIVE_CHANNEL_ID, db[0])
                return

            status = await client.send_message(chat_id, "⏳ در حال دانلود از سرور یوتیوب...")
            
            # تنظیمات یوتوب دی‌ال با تغییرات برای رفع خطاهای احتمالی
            dl_opts = {
                'format': 'ba/b',
                'outtmpl': '%(id)s.%(ext)s',
                'quiet': True,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            }

            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    info = ydl.extract_info(yt_id, download=True)
                    filename = f"{yt_id}.mp3"
                    if os.path.exists(filename):
                        archive_msg = await client.send_document(ARCHIVE_CHANNEL_ID, filename, caption=f"{info.get('title')}\n{yt_id}")
                        save_track_to_db(yt_id, info.get('title', ''), '', archive_msg.id)
                        await client.send_document(chat_id, filename)
                        await status.delete()
            except Exception as e:
                await status.edit_text(f"❌ خطای دانلود:\n{str(e)[:100]}")
            finally:
                cleanup_files(yt_id)

    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

if __name__ == "__main__":
    app.run()
