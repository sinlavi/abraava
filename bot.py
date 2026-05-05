import os
import sqlite3
import yt_dlp
import re
import glob
import json
from ytmusicapi import YTMusic
from balethon import Client
from balethon.conditions import private
from balethon.objects import Message, CallbackQuery, InlineKeyboard, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
ARCHIVE_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "-1000000000000"))

app = Client(BOT_TOKEN)
# اگر برای جستجو هم نیاز به کوکی دارید، باید یک فایل auth.json طبق داکیومنت ytmusicapi بسازید
# در اینجا از حالت پیش‌فرض برای سرچ استفاده می‌کنیم
ytmusic = YTMusic()

# ================= DATABASE & HELPERS =================

def init_db():
    conn = sqlite3.connect('archive.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # جدول ذخیره فایل‌های دانلود شده
    cursor.execute('''CREATE TABLE IF NOT EXISTS tracks_files 
                      (file_key TEXT PRIMARY KEY, message_id INTEGER)''')
    
    # جدول کش متادیتا ترک‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS tracks_meta 
                      (yt_id TEXT PRIMARY KEY, title TEXT, artist TEXT, cover_url TEXT, formats_json TEXT)''')
    
    # جدول کش متادیتا آلبوم‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS albums_meta 
                      (browse_id TEXT PRIMARY KEY, title TEXT, artist TEXT, cover_url TEXT, track_count INTEGER, release_year TEXT, tracks_json TEXT)''')
    
    conn.commit()
    return conn

db_conn = init_db()

def get_cached_track(yt_id):
    c = db_conn.cursor()
    c.execute('SELECT title, artist, cover_url, formats_json FROM tracks_meta WHERE yt_id = ?', (yt_id,))
    return c.fetchone()

def save_track_meta(yt_id, title, artist, cover_url, formats_json):
    c = db_conn.cursor()
    c.execute('INSERT OR REPLACE INTO tracks_meta VALUES (?, ?, ?, ?, ?)', 
              (yt_id, title, artist, cover_url, json.dumps(formats_json)))
    db_conn.commit()

def get_cached_album(browse_id):
    c = db_conn.cursor()
    c.execute('SELECT title, artist, cover_url, track_count, release_year, tracks_json FROM albums_meta WHERE browse_id = ?', (browse_id,))
    return c.fetchone()

def save_album_meta(browse_id, title, artist, cover_url, track_count, release_year, tracks_json):
    c = db_conn.cursor()
    c.execute('INSERT OR REPLACE INTO albums_meta VALUES (?, ?, ?, ?, ?, ?, ?)', 
              (browse_id, title, artist, cover_url, track_count, release_year, json.dumps(tracks_json)))
    db_conn.commit()

def get_track_file(yt_id, format_id):
    c = db_conn.cursor()
    c.execute('SELECT message_id FROM tracks_files WHERE file_key = ?', (f"{yt_id}_{format_id}",))
    row = c.fetchone()
    return row[0] if row else None

def save_track_file(yt_id, format_id, message_id):
    c = db_conn.cursor()
    c.execute('INSERT OR REPLACE INTO tracks_files VALUES (?, ?)', (f"{yt_id}_{format_id}", message_id))
    db_conn.commit()

def extract_video_id(url):
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', url)
    return match.group(1) if match else url

def cleanup_files(yt_id):
    for f in glob.glob(f"{yt_id}.*"):
        try: os.remove(f)
        except: pass

def get_high_res_thumbnail(thumbnails):
    if not thumbnails: return None
    return thumbnails[-1].get('url')

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
        results = ytmusic.search(text, limit=15)
        keyboard = []
        
        for r in results:
            rtype = r.get('resultType')
            if rtype == 'artist' and r.get('browseId'):
                keyboard.append([InlineKeyboardButton(f"🎤 آرتیست: {r.get('artist', 'Unknown')[:20]}", f"art|{r['browseId']}")])
            elif rtype == 'album' and r.get('browseId'):
                keyboard.append([InlineKeyboardButton(f"💿 آلبوم: {r.get('title', 'Unknown')[:20]}", f"alb|{r['browseId']}")])
            elif rtype in ['song', 'video'] and r.get('videoId'):
                keyboard.append([InlineKeyboardButton(f"🎵 ترک: {r.get('title', 'Unknown')[:20]}", f"trk|{r['videoId']}")])

        if not keyboard:
            await wait_msg.edit_text("❌ نتیجه‌ای یافت نشد.")
            return

        await wait_msg.edit_text(f"✅ نتایج جستجو برای: {text}", reply_markup=InlineKeyboard(*keyboard[:10]))
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا در جستجو: {e}")
        
async def send_track_info(client, context, vid):
    is_callback = isinstance(context, CallbackQuery)
    chat_id = context.message.chat.id if is_callback else context.chat.id
    
    cached = get_cached_track(vid)
    if cached:
        title, artist, thumb, formats_json = cached
        formats = json.loads(formats_json)
    else:
        try:
            track_info = ytmusic.get_song(vid)
            vid_details = track_info.get('videoDetails', {})
            title = vid_details.get('title', 'Unknown')
            artist = vid_details.get('author', 'Unknown')
            thumb = get_high_res_thumbnail(vid_details.get('thumbnail', {}).get('thumbnails', []))
            
            # دریافت فرمت‌ها با yt-dlp
            dl_opts = {
                'quiet': True, 
                'cookiefile': 'cookies.txt',
                'extract_flat': False
            }
            formats = []
            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    info = ydl.extract_info(vid, download=False)
                    for f in info.get('formats', []):
                        if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                            formats.append({
                                'format_id': f.get('format_id'),
                                'ext': f.get('ext'),
                                'abr': f.get('abr', 0),
                                'format_note': f.get('format_note', '')
                            })
            except Exception as e:
                print(f"yt-dlp format extraction error: {e}")
                # در صورت خطا، یک فرمت پیش‌فرض قرار می‌دهیم تا ربات از کار نیفتد
                formats = [{'format_id': 'bestaudio', 'ext': 'mp3', 'abr': 128, 'format_note': 'Best'}]
                
            save_track_meta(vid, title, artist, thumb, formats)
        except Exception as e:
            error_text = f"❌ خطا در دریافت اطلاعات: {e}"
            if is_callback:
                await context.message.reply(error_text)
            else:
                await context.reply(error_text)
            return

    caption = f"🎵 عنوان: {title}\n👤 آرتیست: {artist}"
    
    keyboard = []
    if formats:
        for f in sorted(formats, key=lambda x: x['abr'] or 0, reverse=True)[:3]:
            bitrate = int(f['abr']) if f['abr'] else "?"
            btn_text = f"⬇️ دانلود (کیفیت {bitrate}kbps)"
            keyboard.append([InlineKeyboardButton(btn_text, f"dl|{vid}|{f['format_id']}")])
    else:
        # حالت فال‌بک اگر فرمتی پیدا نشد
        keyboard.append([InlineKeyboardButton("⬇️ دانلود بهترین کیفیت", f"dl|{vid}|bestaudio")])
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت / بستن", "close")])

    if thumb:
        await client.send_photo(chat_id, thumb, caption=caption, reply_markup=InlineKeyboard(*keyboard))
    else:
        await client.send_message(chat_id, caption, reply_markup=InlineKeyboard(*keyboard))

@app.on_callback_query()
async def handle_callback(client: Client, callback_query: CallbackQuery):
    query = callback_query
    data = query.data
    chat_id = query.message.chat.id
    action, *args = data.split("|")

    try:
        if action == "art":
            browse_id = args[0]
            artist = ytmusic.get_artist(browse_id)
            name = artist.get('name', 'Unknown')
            desc = artist.get('description', '')[:150] + "..."
            thumb = get_high_res_thumbnail(artist.get('thumbnails', []))
            
            albums_count = len(artist.get('albums', {}).get('results', []))
            songs_count = len(artist.get('songs', {}).get('results', []))
            
            caption = f"🎤 آرتیست: {name}\n"
            caption += f"💿 آلبوم‌های برتر: {albums_count}\n"
            caption += f"🎵 ترک‌های برتر: {songs_count}\n\n"
            caption += f"📝 توضیحات:\n{desc}"
            
            keyboard = []
            if 'songs' in artist and 'results' in artist['songs']:
                for song in artist['songs']['results'][:4]:
                    vid = song.get('videoId')
                    if vid: keyboard.append([InlineKeyboardButton(f"🎵 {song['title'][:25]}", f"trk|{vid}")])
            
            if 'albums' in artist and 'results' in artist['albums']:
                for alb in artist['albums']['results'][:4]:
                    aid = alb.get('browseId')
                    if aid: keyboard.append([InlineKeyboardButton(f"💿 {alb['title'][:25]}", f"alb|{aid}")])
            
            keyboard.append([InlineKeyboardButton("🔙 بستن", "close")])
            
            if thumb:
                await query.message.reply_photo(thumb, caption=caption, reply_markup=InlineKeyboard(*keyboard))
            else:
                await query.message.reply(caption, reply_markup=InlineKeyboard(*keyboard))
            await query.answer('')

        elif action == "alb":
            browse_id = args[0]
            cached = get_cached_album(browse_id)
            
            if cached:
                title, artist_name, thumb, track_count, release_year, tracks_json = cached
                tracks = json.loads(tracks_json)
            else:
                album = ytmusic.get_album(browse_id)
                title = album.get('title', 'Unknown')
                artist_name = album.get('artists', [{'name': 'Unknown'}])[0].get('name', 'Unknown')
                thumb = get_high_res_thumbnail(album.get('thumbnails', []))
                track_count = album.get('trackCount', 0)
                release_year = album.get('year', 'نامشخص')
                
                tracks = []
                for track in album.get('tracks', []):
                    if track.get('videoId'):
                        tracks.append({'title': track['title'], 'videoId': track['videoId']})
                        
                save_album_meta(browse_id, title, artist_name, thumb, track_count, release_year, tracks)

            caption = f"💿 آلبوم: {title}\n👤 آرتیست: {artist_name}\n"
            caption += f"🎶 تعداد ترک‌ها: {track_count}\n📅 سال انتشار: {release_year}"
            
            keyboard = []
            for track in tracks[:10]: # نمایش 10 ترک اول
                keyboard.append([InlineKeyboardButton(f"🎵 {track['title'][:30]}", f"trk|{track['videoId']}")])
                    
            keyboard.append([InlineKeyboardButton("🔙 بستن", "close")])
            
            if thumb:
                await query.message.reply_photo(thumb, caption=caption, reply_markup=InlineKeyboard(*keyboard))
            else:
                await query.message.reply(caption, reply_markup=InlineKeyboard(*keyboard))
            await query.answer('')

        elif action == "trk":
            await query.answer('')
            await send_track_info(client, query, args[0])

        elif action == "close":
            await query.message.delete()
            await query.answer('')

        elif action == "dl":
            yt_id = args[0]
            format_id = args[1]
            await query.answer("در حال پردازش...")
            
            cached_msg_id = get_track_file(yt_id, format_id)
            if cached_msg_id:
                await client.copy_message(chat_id, ARCHIVE_CHANNEL_ID, cached_msg_id)
                return

            status = await client.send_message(chat_id, "⏳ در حال دانلود با کیفیت انتخاب شده...")
            
            # فایل کوکی به تنظیمات اضافه شده است
            dl_opts = {
                'format': format_id,
                'outtmpl': f'{yt_id}_%(ext)s',
                'quiet': True,
                'cookiefile': 'cookies.txt', # استفاده از کوکی‌ها برای عبور از محدودیت‌ها
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            }

            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    info = ydl.extract_info(yt_id, download=True)
                    filename = f"{yt_id}_mp3.mp3" # خروجی postprocessor
                    
                    if os.path.exists(filename):
                        cap = f"🎵 {info.get('title')}\n📥 کیفیت: فرمت {format_id}"
                        archive_msg = await client.send_document(ARCHIVE_CHANNEL_ID, filename, caption=cap)
                        save_track_file(yt_id, format_id, archive_msg.id)
                        await client.send_document(chat_id, filename, caption=cap)
                        await status.delete()
                    else:
                         await status.edit_text("❌ خطا در یافتن فایل دانلود شده.")
            except Exception as e:
                await status.edit_text(f"❌ خطای دانلود:\n{str(e)[:100]}")
            finally:
                cleanup_files(yt_id)

    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

if __name__ == "__main__":
    app.run()
