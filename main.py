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

def fetch_songlink_priority_url(data):
    platforms = data.get("linksByPlatform", {})
    return (
        platforms.get("soundcloud", {}).get("url") or
        platforms.get("youtube", {}).get("url")
    )

def format_meta(meta):
    return (
        f"\U0001F3B5 *{meta.get('trackName')}*\n"
        f"\U0001F464 {meta.get('artistName')}\n"
        f"🖼 {meta.get('collectionName')}\n"
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

async def send_song_info(chat_id, meta, song_data):
    caption = format_meta(meta)
    img = meta.get("artworkUrl100", "").replace("100x100", "600x600")
    tid = str(uuid4())
    download_links[tid] = song_data

    keyboard = []
    preview = meta.get("previewUrl")
    if preview:
        keyboard.append([{"text": "🎧 پخش پیش‌نمایش", "callback_data": f"preview_{preview}"}])

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

    results = search_soundcloud(text) + search_itunes(text)
    if not results:
        return await bot.send_message(chat_id, "⚠️ هیچ نتیجه‌ای یافت نشد.")

    keyboard = []
    search_cache[chat_id] = {}

    for item in results[:10]:
        title = item.get("title") or item.get("trackName") or "بی‌نام"
        url = item.get("webpage_url") or item.get("trackViewUrl")
        if not url:
            continue
        sid = str(uuid4())
        search_cache[chat_id][sid] = url
        keyboard.append([{
            "text": f"🎵 {title[:40]}",
            "callback_data": f"resolve|{sid}"
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

    if data.startswith("preview_"):
        url = data[8:]
        return await bot.send_voice(chat_id, voice=url)

    elif data.startswith("download_"):
        tid = data[9:]
        song_data = download_links.get(tid)
        if not song_data:
            return await bot.send_message(chat_id, "❌ لینک دانلود موجود نیست.")

        url = fetch_songlink_priority_url(song_data)
        if url:
            await callback_query.answer("⬇️ در حال دانلود...")
            return await download_and_send(chat_id, url)
        else:
            return await bot.send_message(chat_id, "❌ فایل قابل دانلود نیست.")

    elif data.startswith("resolve|"):
        sid = data.split("|", 1)[1]
        if chat_id not in search_cache or sid not in search_cache[chat_id]:
            return await callback_query.answer("⛔ لینک پیدا نشد.")

        url = search_cache[chat_id][sid]
        await callback_query.answer("⏳ دریافت اطلاعات...")

        song_data = fetch_songlink(url)
        if not song_data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با Song.link")

        meta = extract_itunes(song_data)
        if meta:
            return await send_song_info(chat_id, meta, song_data)

        fallback_url = fetch_songlink_priority_url(song_data)
        if fallback_url:
            return await download_and_send(chat_id, fallback_url)
        else:
            return await bot.send_message(chat_id, "❌ هیچ لینکی برای دانلود یافت نشد.")

bot.run()
