import os
import asyncio
import time
import requests
from uuid import uuid4
from balethon import Client
from yt_dlp import YoutubeDL

bot = Client("1011430416:V6rCwbls3JUS38Zq9GZrGfMeRF2VDuPtVMaVxEWH")

search_cache = {}
download_links = {}
meta_cache = {}

def search_soundcloud(query):
    with YoutubeDL({"quiet": True}) as ydl:
        try:
            return ydl.extract_info(f"scsearch5:{query}", download=False)["entries"]
        except:
            return []

def search_itunes(query):
    try:
        res = requests.get("https://itunes.apple.com/search", params={
            "term": query,
            "media": "music",
            "limit": 5
        })
        return res.json().get("results", [])
    except:
        return []

def fetch_songlink(url):
    try:
        r = requests.get("https://api.song.link/v1-alpha.1/links", params={"url": url})
        return r.json() if r.status_code == 200 else None
    except:
        return None

def extract_itunes(data):
    platforms = data.get("linksByPlatform", {})
    itunes = platforms.get("itunes", {})
    eid = itunes.get("entityUniqueId")
    return data.get("entitiesByUniqueId", {}).get(eid)

def format_meta(meta):
    return (
        f"🎵 *{meta.get('trackName')}*\n"
        f"👤 {meta.get('artistName')}\n"
        f"💿 {meta.get('collectionName')}\n"
        f"📅 {meta.get('releaseDate', '')[:10]}\n"
        f"🎧 {meta.get('primaryGenreName', '-')}"
    )

def delete_file(path):
    if os.path.exists(path):
        os.remove(path)

async def download_and_send(chat_id, url):
    filename = f"{uuid4()}.mp3"
    msg = await bot.send_message(chat_id, "⏳ در حال دانلود فایل...")

    last_update_time = 0

    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update_time >= 1:
                percent = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '').strip()
                eta = d.get('_eta_str', '').strip()
                text = f"⬇️ در حال دانلود...\nدرصد: {percent}\nسرعت: {speed}\nزمان: {eta}"
                asyncio.create_task(bot.edit_message_text(chat_id, msg.id, text))
                last_update_time = now

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": filename,
        "quiet": True,
        "progress_hooks": [progress_hook],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        await bot.edit_message_text(chat_id, msg.id, "⛔ خطا در دانلود فایل.")
        return

    try:
        with open(filename, 'rb') as f:
            await bot.send_audio(chat_id, audio=f)
    except Exception as e:
        await bot.send_message(chat_id, f"⛔ خطا در ارسال فایل: {e}")
    finally:
        delete_file(filename)

async def send_song_info(chat_id, meta, tid):
    caption = format_meta(meta)
    img = meta.get("artworkUrl100", "").replace("100x100", "600x600")
    keyboard = []

    preview = meta.get("previewUrl")
    if preview:
        keyboard.append([{"text": "🎧 پخش پیش‌نمایش", "callback_data": f"preview_{preview}"}])

    if tid in download_links:
        keyboard.append([{"text": "⬇️ دریافت فایل", "callback_data": f"download_{tid}"}])

    await bot.send_photo(
        chat_id=chat_id,
        photo=img,
        caption=caption,
        reply_markup={"inline_keyboard": keyboard}
    )

@bot.on_message()
async def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if not text:
        return await bot.send_message(chat_id, "لطفاً نام آهنگ را بفرست.")

    sc_results = search_soundcloud(text)
    itunes_results = search_itunes(text)

    if not sc_results and not itunes_results:
        return await bot.send_message(chat_id, "⚠️ هیچ نتیجه‌ای یافت نشد.")

    keyboard = []
    search_cache[chat_id] = {}

    for item in sc_results[:5]:
        title = item.get("title", "بی‌نام")
        url = item.get("webpage_url")
        sid = str(uuid4())
        search_cache[chat_id][sid] = url
        keyboard.append([{
            "text": f"🎧 {title[:40]} (SoundCloud)",
            "callback_data": f"meta|{sid}"
        }])

    for item in itunes_results[:5]:
        track = item.get("trackName", "بی‌نام")
        artist = item.get("artistName", "نامشخص")
        view_url = item.get("trackViewUrl", "")
        keyboard.append([{
            "text": f"🎵 {track} – {artist} (iTunes)",
            "url": view_url
        }])

    await bot.send_message(
        chat_id,
        "🎶 نتایج جستجو:",
        reply_markup={"inline_keyboard": keyboard}
    )

@bot.on_callback_query()
async def handle_callback(callback_query):
    chat_id = callback_query.message.chat.id
    data = callback_query.data

    if data.startswith("meta|"):
        sid = data.split("|", 1)[1]
        if chat_id not in search_cache or sid not in search_cache[chat_id]:
            return await callback_query.answer("⛔ لینک یافت نشد.")
        url = search_cache[chat_id][sid]

        await callback_query.answer("🔍 دریافت اطلاعات...")

        songlink_data = fetch_songlink(url)
        if not songlink_data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")

        meta = extract_itunes(songlink_data)
        if not meta:
            return await bot.send_message(chat_id, "⚠️ متادیتا یافت نشد")

        download_links[sid] = url
        meta_cache[sid] = meta
        await send_song_info(chat_id, meta, sid)

    elif data.startswith("preview_"):
        url = data[8:]
        await bot.send_voice(chat_id, voice=url)

    elif data.startswith("download_"):
        sid = data[9:]
        url = download_links.get(sid)
        if not url:
            return await bot.send_message(chat_id, "❌ لینک دانلود موجود نیست.")
        await callback_query.answer("⬇️ شروع دانلود...")
        await download_and_send(chat_id, url)

bot.run()
