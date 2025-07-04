import os
import re
import requests
from uuid import uuid4
from balethon import Client
from yt_dlp import YoutubeDL
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, error
from mutagen.mp3 import MP3

bot = Client("1011430416:V6rCwbls3JUS38Zq9GZrGfMeRF2VDuPtVMaVxEWH")  # توکن ربات Bale
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

def download_audio_yt_dlp(url, meta):
    filename = f"{uuid4()}.mp3"
    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'format': 'bestaudio/best',
        'outtmpl': filename,
        'quiet': True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    try:
        audio = MP3(filename, ID3=ID3)

        try:
            audio.add_tags()
        except error:
            pass

        audio["TIT2"] = meta.get("trackName", "")
        audio["TPE1"] = meta.get("artistName", "")
        audio["TALB"] = meta.get("collectionName", "")
        audio["TCON"] = meta.get("primaryGenreName", "")
        audio["TDRC"] = meta.get("releaseDate", "")[:4]  # سال انتشار

        cover_url = meta.get("artworkUrl100", "").replace("100x100", "600x600")
        if cover_url:
            r = requests.get(cover_url)
            if r.status_code == 200:
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc=u'Cover',
                        data=r.content
                    )
                )
        audio.save()
    except Exception as e:
        print("Error setting metadata:", e)

    return filename

def delete_file(path: str):
    if os.path.exists(path):
        os.remove(path)

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

    results = search_itunes(text)
    if not results:
        return await bot.send_message(chat_id, "نتیجه‌ای یافت نشد.")

    keyboard = []
    for r in results:
        tid = str(r["trackId"])
        itunes_cache[tid] = r
        keyboard.append([{"text": f"{r['trackName']} – {r['artistName']}", "callback_data": f"t_{tid}"}])

    await bot.send_message(chat_id, "🎶 نتایج جستجو:", reply_markup={"inline_keyboard": keyboard})

@bot.on_callback_query()
async def answer_callback_query(callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id

    if data.startswith("t_"):
        tid = data[2:]
        meta = itunes_cache.get(tid)
        if not meta:
            return await callback_query.answer("❌ اطلاعات یافت نشد.")

        track_url = meta.get("trackViewUrl")
        songlink_data = fetch_songlink(track_url) if track_url else None
        if not songlink_data:
            return await bot.send_message(chat_id, "⛔ خطا در ارتباط با song.link")

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

        # اینجا متا را از کش itunes می‌گیریم تا متادیتا را ست کنیم
        meta = itunes_cache.get(tid)
        path = download_audio_yt_dlp(url, meta)
        if not path:
            return await bot.send_message(chat_id, "⛔ خطا در دانلود فایل.")

        await bot.send_audio(chat_id, audio=path)
        delete_file(path)

bot.run()
