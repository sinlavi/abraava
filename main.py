import os
import re
import requests
import asyncio
from uuid import uuid4
from balethon import Client
from yt_dlp import YoutubeDL

bot = Client("1011430416:V6rCwbls3JUS38Zq9GZrGfMeRF2VDuPtVMaVxEWH")

itunes_cache = {}
platform_cache = {}
download_links = {}

PLATFORM_NAMES_FA = {
    "soundcloud": "پخش در ساندکلاود",
    "youtube": "پخش در یوتیوب",
    "spotify": "پخش در اسپاتیفای",
    "appleMusic": "پخش در اپل موزیک",
    "itunes": "پخش در آیتونز",
    "amazonStore": "فروشگاه آمازون",
    "deezer": "پخش در دیزر",
    "pandora": "پخش در پاندورا",
    "amazonMusic": "آمازون موزیک",
    "anghami": "انگامی",
    "napster": "نپستر",
    "tidal": "تایدال",
    "boomplay": "بوم‌پلی",
    "lineMusic": "لاین موزیک",
    "shazam": "شزم",
    "spinrilla": "اسپینریلا",
    "audiomack": "آدیومک",
    "google": "گوگل",
    "instagram": "اینستاگرام",
    "twitter": "توییتر",
    "facebook": "فیسبوک",
    "soundbuzz": "ساندباز",
    "youtubeMusic": "یوتیوب موزیک",
    "yandex": "یاندکس"
}

SOCIAL_PLATFORMS = ["instagram", "twitter", "facebook", "shazam", "google", "yandex"]

def contains_url(text):
    return bool(re.search(r"https?://", text))

def fetch_songlink(url):
    r = requests.get("https://api.song.link/v1-alpha.1/links", params={"url": url})
    print(r)
    return r.json() if r.status_code == 200 else None

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
        f"🎵 *{meta.get('trackName')}*\n"
        f"👤 {meta.get('artistName')}\n"
        f"💿 {meta.get('collectionName')}\n"
        f"📅 {meta.get('releaseDate', '')[:10]}\n"
        f"🎧 {meta.get('primaryGenreName', '-')}"
    )

def search_itunes(query):
    r = requests.get("https://itunes.apple.com/search", params={
        "term": query,
        "media": "music",
        "limit": 5
    })
    return r.json().get("results", [])

def search_soundcloud(query):
    with YoutubeDL({"quiet": True}) as ydl:
        try:
            results = ydl.extract_info(f"scsearch5:{query}", download=False)['entries']
            return results
        except Exception:
            return []

def separate_buttons(data, meta):
    platforms = data.get("linksByPlatform", {})
    tid = str(meta.get("trackId") or meta.get("trackViewUrl") or "0")
    platform_cache[tid] = []

    for platform, info in platforms.items():
        url = info.get("url")
        if not url or platform in SOCIAL_PLATFORMS:
            continue
        fa_name = PLATFORM_NAMES_FA.get(platform, f"پخش در {platform}")
        platform_cache[tid].append({"text": fa_name, "url": url})

    download_url = fetch_songlink_priority_url(data)
    if download_url:
        download_links[tid] = download_url

    return tid

def delete_file(path: str):
    if os.path.exists(path):
        os.remove(path)

async def download_audio_yt_dlp_async(url, chat_id):
    filename = f"{uuid4()}.mp3"
    message = await bot.send_message(chat_id, "⏳ شروع دانلود...")

    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '').strip()
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            progress_text = f"⬇️ در حال دانلود...\nدرصد: {percent}\nسرعت: {speed}\nزمان باقی‌مانده: {eta}"
            asyncio.create_task(bot.edit_message_text(chat_id=chat_id, message_id=message.id, text=progress_text))

    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'format': 'bestaudio/best',
        'outtmpl': filename,
        'quiet': True,
        'progress_hooks': [progress_hook],
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return filename

async def send_song_info(chat_id, meta, data):
    caption = format_meta(meta)
    img = meta.get("artworkUrl100", "").replace("100x100", "600x600")
    tid = separate_buttons(data, meta)

    keyboard = []

    preview = meta.get("previewUrl")
    if preview:
        keyboard.append([{"text": "🎧 پخش پیش‌نمایش", "callback_data": f"preview_{preview}"}])

    if tid in download_links:
        keyboard.append([{"text": "⬇️ دریافت فایل", "callback_data": f"download_{tid}"}])

    keyboard.append([{"text": "🌐 شبکه‌های پخش", "callback_data": f"platforms_{tid}"}])

    await bot.send_photo(
        chat_id=chat_id,
        photo=img,
        caption=caption,
        reply_markup={"inline_keyboard": keyboard}
    )

@bot.on_message()
async def on_message(message):
    text = message.text
    chat_id = message.chat.id

    if contains_url(text):
        data = fetch_songlink(text)
        if not data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")

        meta = extract_itunes(data)
        if not meta:
            return await bot.send_message(chat_id, "⚠️ متادیتا یافت نشد")

        return await send_song_info(chat_id, meta, data)

    # Search both
    itunes_results = search_itunes(text)
    soundcloud_results = search_soundcloud(text)

    if not itunes_results and not soundcloud_results:
        return await bot.send_message(chat_id, "نتیجه‌ای یافت نشد.")

    keyboard = []

    for r in itunes_results:
        tid = str(r["trackId"])
        itunes_cache[tid] = r
        keyboard.append([{"text": f"🎵 {r['trackName']} – {r['artistName']}", "callback_data": f"t_{tid}"}])

    for sc in soundcloud_results:
        scid = f"sc_{sc['id']}"
        itunes_cache[scid] = sc
        title = sc.get("title", "بی‌نام")
        uploader = sc.get("uploader", "")
        keyboard.append([{"text": f"🎧 {title} – {uploader}", "callback_data": scid}])

    await bot.send_message(chat_id, "🎶 نتایج جستجو:", reply_markup={"inline_keyboard": keyboard})

@bot.on_callback_query()
async def answer_callback_query(callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id

    if data.startswith("t_"):
        tid = data[2:]
        meta = itunes_cache.get(tid)
        print(tid)
        print(meta)
        if not meta:
            return await callback_query.answer("❌ اطلاعات یافت نشد.")

        track_url = meta.get("trackViewUrl")
        songlink_data = fetch_songlink(track_url) if track_url else None
        if not songlink_data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")

        await send_song_info(chat_id, meta, songlink_data)

    elif data.startswith("sc_"):
        sc_meta = itunes_cache.get(data)
        if not sc_meta:
            return await callback_query.answer("❌ اطلاعات SoundCloud یافت نشد.")

        url = sc_meta.get("webpage_url")
        if not url:
            return await bot.send_message(chat_id, "⛔ لینک SoundCloud یافت نشد.")

        songlink_data = fetch_songlink(url)
        if not songlink_data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")

        meta = {
            "trackName": sc_meta.get("title", "بدون عنوان"),
            "artistName": sc_meta.get("uploader", "نامشخص"),
            "collectionName": sc_meta.get("uploader", "SoundCloud"),
            "releaseDate": sc_meta.get("upload_date", ""),
            "primaryGenreName": sc_meta.get("genre", "SoundCloud"),
            "artworkUrl100": sc_meta.get("thumbnail"),
            "previewUrl": sc_meta.get("url"),
            "trackId": data
        }

        await send_song_info(chat_id, meta, songlink_data)

    elif data.startswith("platforms_"):
        tid = data[10:]
        buttons = platform_cache.get(tid)
        if not buttons:
            return await callback_query.answer("❌ پلتفرمی یافت نشد.")
        keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        await bot.send_message(chat_id, "🎧 پلتفرم‌های پخش:", reply_markup={"inline_keyboard": keyboard})

    elif data.startswith("preview_"):
        url = data[8:]
        await bot.send_voice(chat_id, voice=url)

    elif data.startswith("download_"):
        tid = data[9:]
        url = download_links.get(tid)
        if not url:
            return await bot.send_message(chat_id, "❌ لینک دانلود موجود نیست.")

        await callback_query.answer("⬇️ در حال دریافت فایل...")

        path = await download_audio_yt_dlp_async(url, chat_id)
        if not path:
            return await bot.send_message(chat_id, "⛔ خطا در دانلود فایل.")

        await bot.send_audio(chat_id, audio=path)
        delete_file(path)

bot.run()
