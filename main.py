import os
import asyncio
import time
from uuid import uuid4
from balethon import Client
from yt_dlp import YoutubeDL
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

bot = Client("1011430416:V6rCwbls3JUS38Zq9GZrGfMeRF2VDuPtVMaVxEWH")

search_cache = {}

def search_soundcloud(query):
    with YoutubeDL({"quiet": True}) as ydl:
        try:
            return ydl.extract_info(f"scsearch5:{query}", download=False)["entries"]
        except:
            return []

def delete_file(path):
    if os.path.exists(path):
        os.remove(path)

def set_metadata(mp3_path, info):
    try:
        audio = MP3(mp3_path, ID3=EasyID3)
        audio["title"] = info.get("title", "Unknown")
        audio["artist"] = info.get("uploader", "Unknown")
        audio["genre"] = info.get("genre", "Unknown")
        if info.get("upload_date"):
            audio["date"] = info["upload_date"]
        audio.save()
    except Exception as e:
        print("Metadata Error:", e)

async def download_and_send(chat_id, url):
    filename = f"{uuid4()}.mp3"
    msg = await bot.send_message(chat_id, "⏳ در حال دانلود فایل...")

    last_update_time = 0
    download_info = {}

    def progress_hook(d):
        nonlocal last_update_time, download_info
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update_time >= 1:
                percent = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '').strip()
                eta = d.get('_eta_str', '').strip()
                text = f"⬇️ در حال دانلود...\nدرصد: {percent}\nسرعت: {speed}\nزمان: {eta}"
                asyncio.create_task(bot.edit_message_text(chat_id, msg.id, text))
                last_update_time = now
        elif d['status'] == 'finished':
            download_info['info'] = d.get('info_dict', {})

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

    info = download_info.get("info", {})
    set_metadata(filename, info)

    # 🔧 تغییر این بخش:
    try:
        with open(filename, 'rb') as f:
            await bot.send_audio(chat_id, audio=f)
    except Exception as e:
        await bot.send_message(chat_id, f"⛔ خطا در ارسال فایل: {e}")
    finally:
        delete_file(filename)

@bot.on_message()
async def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if not text:
        return await bot.send_message(chat_id, "لطفاً نام آهنگ را بفرست.")

    results = search_soundcloud(text)
    if not results:
        return await bot.send_message(chat_id, "⚠️ هیچ نتیجه‌ای یافت نشد.")

    keyboard = []
    search_cache[chat_id] = {}

    for i, item in enumerate(results[:5]):
        title = item.get("title", "بدون عنوان")
        url = item.get("webpage_url")
        sid = str(uuid4())
        search_cache[chat_id][sid] = url
        keyboard.append([{
            "text": f"🎵 {title[:40]}",
            "callback_data": f"dl|{sid}"
        }])

    await bot.send_message(
        chat_id,
        "🎶 نتایج جستجوی SoundCloud:",
        reply_markup={"inline_keyboard": keyboard}
    )

@bot.on_callback_query()
async def handle_callback(callback_query):
    chat_id = callback_query.message.chat.id
    data = callback_query.data

    if not data.startswith("dl|"):
        return await callback_query.answer("❌ دستور نامعتبر است.")

    sid = data.split("|", 1)[1]

    if chat_id not in search_cache or sid not in search_cache[chat_id]:
        return await callback_query.answer("⛔ مورد پیدا نشد.")

    url = search_cache[chat_id][sid]
    await callback_query.answer("⬇️ شروع دانلود...")
    await download_and_send(chat_id, url)

bot.run()
