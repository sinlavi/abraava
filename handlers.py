# handlers.py
import logging

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from yt_dlp import YoutubeDL
from uuid import uuid4
from caches import SEARCH_CACHE, DOWNLOAD_CACHE
from utils import fetch_songlink, extract_itunes, fetch_songlink_priority_url, format_meta
from downloads import download_and_send


# ------------------------
# SEARCH HANDLER
# ------------------------


class Searcher:
    ITUNES_URL = "https://itunes.apple.com/search"

    @staticmethod
    def search_soundcloud(query: str, limit: int = 10):
        logging.info(f"Searching SoundCloud for: {query}")
        with YoutubeDL({"quiet": True}) as ydl:
            try:
                return ydl.extract_info(f"scsearch5:{query}", download=False)["entries"]
            except Exception as e:
                logging.error(f"SoundCloud search error: {e}")
                return []

    @staticmethod
    def search_itunes(query: str, limit: int = 10):
        logging.info(f"Searching iTunes for: {query}")
        try:
            res = requests.get(Searcher.ITUNES_URL, params={
                "term": query,
                "media": "music",
                "limit": limit
            })
            return res.json().get("results", [])
        except Exception as e:
            logging.error(f"iTunes search error: {e}")
            return []

    @staticmethod
    def search(query: str):
        """Unified search across SoundCloud and iTunes"""
        results = []
        """results.extend(Searcher.search_soundcloud(query))"""
        results.extend(Searcher.search_itunes(query, limit=10))
        return results


# ------------------------
# TELEGRAM HANDLERS
# ------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # Check if user clicked a previous keyboard button
    if chat_id in SEARCH_CACHE and text in SEARCH_CACHE[chat_id]:
        url = SEARCH_CACHE[chat_id][text]
        await update.message.reply_text(f"⏳ دریافت اطلاعات آهنگ...")
        song_data = fetch_songlink(url)
        if song_data:
            fallback_url = fetch_songlink_priority_url(song_data)
            if fallback_url:
                await download_and_send(update, context, fallback_url)
            else:
                await context.bot.send_message(chat_id, "❌ هیچ لینکی برای دانلود یافت نشد.")
        else:
            await context.bot.send_message(chat_id, "⛔ خطا در ارتباط با Song.link")
        return

    # Regular search flow
    if not text:
        return await context.bot.send_message(chat_id, "لطفاً نام آهنگ را بفرست.")

    logging.info(f"Received message: {text}")
    results = Searcher.search(text)
    if not results:
        return await context.bot.send_message(chat_id, "⚠️ هیچ نتیجه‌ای یافت نشد.")

    if chat_id not in SEARCH_CACHE:
        SEARCH_CACHE[chat_id] = {}

    keyboard = []
    row = []

    for item in results[:10]:
        title = item.get("title") or item.get("trackName") or "بی‌نام"
        url = item.get("webpage_url") or item.get("trackViewUrl")
        if not url:
            continue

        # Map the title to the URL in cache
        SEARCH_CACHE[chat_id][title] = url

        # Add button showing the title
        row.append(KeyboardButton(title[:30]))  # truncate to fit nicely
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await context.bot.send_message(
        chat_id,
        "🎶 نتایج جستجو (روی نام آهنگ کلیک کنید):",
        reply_markup=reply_markup
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    logging.info(f"Callback received: {data}")

    if data.startswith("preview_"):
        url = data[8:]
        await context.bot.send_voice(chat_id, voice=url)

    elif data.startswith("download_"):
        tid = data[9:]
        song_data = DOWNLOAD_CACHE.get(tid)
        if not song_data:
            await context.bot.send_message(chat_id, "❌ لینک دانلود موجود نیست.")
            return
        url = fetch_songlink_priority_url(song_data)
        if url:
            await query.edit_message_text("⬇️ در حال دانلود...")
            await download_and_send(update, context, url)
        else:
            await context.bot.send_message(chat_id, "❌ فایل قابل دانلود نیست.")

    elif data.startswith("resolve|"):
        sid = data.split("|", 1)[1]
        if chat_id not in SEARCH_CACHE or sid not in SEARCH_CACHE[chat_id]:
            await query.answer("⛔ لینک پیدا نشد.", show_alert=True)
            return

        url = SEARCH_CACHE[chat_id][sid]
        await query.edit_message_text("⏳ دریافت اطلاعات...")

        song_data = fetch_songlink(url)
        if not song_data:
            await context.bot.send_message(chat_id, "⛔ خطا در ارتباط با Song.link")
            return

        meta = extract_itunes(song_data)
        if meta:
            tid = str(uuid4())
            DOWNLOAD_CACHE[tid] = song_data
            from utils import format_meta
            caption = format_meta(meta)
            keyboard = []
            preview = meta.get("previewUrl")
            if preview:
                keyboard.append([InlineKeyboardButton("🎧 پخش پیش‌نمایش", callback_data=f"preview_{preview}")])
            keyboard.append([InlineKeyboardButton("⬇️ دریافت فایل", callback_data=f"download_{tid}")])

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=meta.get("artworkUrl100", "").replace("100x100", "600x600"),
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        fallback_url = fetch_songlink_priority_url(song_data)
        if fallback_url:
            await download_and_send(update, context, fallback_url)
        else:
            await context.bot.send_message(chat_id, "❌ هیچ لینکی برای دانلود یافت نشد.")
