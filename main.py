import os
import re
import json
import requests
import asyncio
from uuid import uuid4
from collections import defaultdict
from balethon import Client
from yt_dlp import YoutubeDL

bot = Client("1011430416:V6rCwbls3JUS38Zq9GZrGfMeRF2VDuPtVMaVxEWH")  # ← توکن اصلی شما

PLATFORM_NAMES_FA = {
    "soundcloud": "پخش در ساندکلاود", "youtube": "پخش در یوتیوب", "spotify": "پخش در اسپاتیفای",
    "appleMusic": "پخش در اپل موزیک", "itunes": "پخش در آیتونز", "amazonStore": "فروشگاه آمازون",
    "deezer": "پخش در دیزر", "pandora": "پخش در پاندورا", "amazonMusic": "آمازون موزیک",
    "anghami": "انگامی", "napster": "نپستر", "tidal": "تایدال", "boomplay": "بوم‌پلی",
    "lineMusic": "لاین موزیک", "shazam": "شزم", "spinrilla": "اسپینریلا", "audiomack": "آدیومک",
    "google": "گوگل", "instagram": "اینستاگرام", "twitter": "توییتر", "facebook": "فیسبوک",
    "soundbuzz": "ساندباز", "youtubeMusic": "یوتیوب موزیک", "yandex": "یاندکس"
}
SOCIAL_PLATFORMS = ["instagram", "twitter", "facebook", "shazam", "google", "yandex"]

# کش متادیتا برای هر کاربر
user_meta_cache = defaultdict(dict)

def contains_url(text):
    return bool(re.search(r"https?://", text))

def fetch_songlink(url):
    r = requests.get("https://api.song.link/v1-alpha.1/links", params={"url": url})
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
        "term": query, "media": "music", "limit": 5
    })
    return r.json().get("results", [])

def search_soundcloud(query):
    with YoutubeDL({"quiet": True}) as ydl:
        try:
            return ydl.extract_info(f"scsearch5:{query}", download=False)["entries"]
        except:
            return []

def delete_file(path: str):
    if os.path.exists(path):
        os.remove(path)

async def download_audio_yt_dlp_async(url, chat_id):
    filename = f"{uuid4()}.mp3"
    msg = await bot.send_message(chat_id, "⏳ شروع دانلود...")

    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '').strip()
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            text = f"⬇️ در حال دانلود...\nدرصد: {percent}\nسرعت: {speed}\nزمان باقی‌مانده: {eta}"
            asyncio.create_task(bot.edit_message_text(chat_id, msg.id, text))

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
    tid = str(uuid4())

    keyboard = []
    user_meta_cache[chat_id][tid] = (meta, data)

    if meta.get("previewUrl"):
        keyboard.append([{
            "text": "🎧 پخش پیش‌نمایش", "callback_data": f"preview|{meta['previewUrl']}"
        }])

    download_url = fetch_songlink_priority_url(data)
    if download_url:
        keyboard.append([{
            "text": "⬇️ دریافت فایل", "callback_data": f"download|{download_url}"
        }])

    keyboard.append([{
        "text": "🌐 شبکه‌های پخش", "callback_data": f"platforms|{tid}"
    }])

    await bot.send_photo(
        chat_id=chat_id,
        photo=img,
        caption=caption,
        reply_markup={"inline_keyboard": keyboard}
    )

@bot.on_message()
async def on_message(message):
    chat_id = message.chat.id
    text = message.text

    if contains_url(text):
        data = fetch_songlink(text)
        if not data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")
        meta = extract_itunes(data)
        if not meta:
            return await bot.send_message(chat_id, "⚠️ متادیتا یافت نشد")
        return await send_song_info(chat_id, meta, data)

    itunes_results = search_itunes(text)
    soundcloud_results = search_soundcloud(text)
    if not itunes_results and not soundcloud_results:
        return await bot.send_message(chat_id, "نتیجه‌ای یافت نشد.")

    keyboard = []
    for result in itunes_results:
        tid = str(uuid4())
        meta = result
        url = meta.get("trackViewUrl")
        data = fetch_songlink(url) if url else None
        if not data:
            continue
        user_meta_cache[chat_id][tid] = (meta, data)
        keyboard.append([{
            "text": f"🎵 {meta['trackName']} – {meta['artistName']}",
            "callback_data": f"meta|{tid}"
        }])

    for sc in soundcloud_results:
        url = sc.get("webpage_url")
        data = fetch_songlink(url) if url else None
        if not data:
            continue
        meta = {
            "trackName": sc.get("title", "بدون عنوان"),
            "artistName": sc.get("uploader", "نامشخص"),
            "collectionName": sc.get("uploader", "SoundCloud"),
            "releaseDate": sc.get("upload_date", ""),
            "primaryGenreName": sc.get("genre", "SoundCloud"),
            "artworkUrl100": sc.get("thumbnail", ""),
            "previewUrl": sc.get("url"),
        }
        tid = str(uuid4())
        user_meta_cache[chat_id][tid] = (meta, data)
        keyboard.append([{
            "text": f"🎧 {meta['trackName']} – {meta['artistName']}",
            "callback_data": f"meta|{tid}"
        }])

    await bot.send_message(chat_id, "🎶 نتایج جستجو:", reply_markup={"inline_keyboard": keyboard})

@bot.on_callback_query()
async def on_callback(callback_query):
    chat_id = callback_query.message.chat.id
    data = callback_query.data

    if data.startswith("meta|"):
        tid = data.split("|", 1)[1]
        meta_pair = user_meta_cache[chat_id].get(tid)
        if not meta_pair:
            return await callback_query.answer("❌ اطلاعات یافت نشد.")
        meta, songlink_data = meta_pair
        await send_song_info(chat_id, meta, songlink_data)

    elif data.startswith("preview|"):
        url = data.split("|", 1)[1]
        await bot.send_voice(chat_id, voice=url)

    elif data.startswith("download|"):
        url = data.split("|", 1)[1]
        await callback_query.answer("⬇️ در حال دریافت فایل...")
        path = await download_audio_yt_dlp_async(url, chat_id)
        await bot.send_audio(chat_id, audio=path)
        delete_file(path)

    elif data.startswith("platforms|"):
        tid = data.split("|", 1)[1]
        meta_pair = user_meta_cache[chat_id].get(tid)
        if not meta_pair:
            return await callback_query.answer("❌ اطلاعات یافت نشد.")
        _, data = meta_pair
        platforms = data.get("linksByPlatform", {})
        buttons = []
        for platform, info in platforms.items():
            if not info.get("url") or platform in SOCIAL_PLATFORMS:
                continue
            fa = PLATFORM_NAMES_FA.get(platform, f"پخش در {platform}")
            buttons.append({"text": fa, "url": info["url"]})
        grouped = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        await bot.send_message(chat_id, "🌐 پلتفرم‌های پخش:", reply_markup={"inline_keyboard": grouped})

bot.run()
