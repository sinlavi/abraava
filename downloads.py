# downloads.py
import asyncio
import time
from uuid import uuid4
from yt_dlp import YoutubeDL
from telegram import Update
from telegram.ext import ContextTypes
import logging
from utils import delete_file

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    chat_id = update.effective_chat.id
    filename = f"{uuid4()}.mp3"
    msg = await context.bot.send_message(chat_id, "⏳ در حال دانلود فایل...")

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
                asyncio.create_task(context.bot.edit_message_text(chat_id, msg.message_id, text))
                last_update_time = now

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": filename,
        "quiet": True,
        "progress_hooks": [progress_hook],
    }

    try:
        logging.info(f"Downloading URL: {url}")
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logging.error(f"Download error: {e}")
        await context.bot.edit_message_text(chat_id, msg.message_id, "⛔ خطا در دانلود فایل.")
        return

    try:
        with open(filename, 'rb') as f:
            logging.info(f"Sending file: {filename}")
            await context.bot.send_audio(chat_id, audio=f)
    except Exception as e:
        logging.error(f"Send audio error: {e}")
        await context.bot.send_message(chat_id, f"⛔ خطا در ارسال فایل: {e}")
    finally:
        delete_file(filename)
