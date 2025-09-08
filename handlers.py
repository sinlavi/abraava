# handlers.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
        results = []
        # results.extend(Searcher.search_soundcloud(query))  # optional
        results.extend(Searcher.search_itunes(query, limit=10))
        return results

# ------------------------
# TELEGRAM HANDLERS
# ------------------------
async def handle_message(update, context):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if not text:
        return await context.bot.send_message(chat_id, "لطفاً نام آهنگ را بفرست.")

    logging.info(f"Received message: {text}")
    results = Searcher.search(text)
    if not results:
        return await context.bot.send_message(chat_id, "⚠️ هیچ نتیجه‌ای یافت نشد.")

    if chat_id not in SEARCH_CACHE:
        SEARCH_CACHE[chat_id] = {}

    keyboard = []
    for item in results[:10]:
        title = item.get("title") or item.get("trackName") or "بی‌نام"
        url = item.get("webpage_url") or item.get("trackViewUrl")
        if not url:
            continue

        SEARCH_CACHE[chat_id][title] = url
        tid = str(uuid4())
        DOWNLOAD_CACHE[tid] = {"url": url}  # minimal entry
        keyboard.append([InlineKeyboardButton(title[:30], callback_data=f"resolve|{tid}")])

    await context.bot.send_message(
        chat_id,
        "🎶 نتایج جستجو (روی نام آهنگ کلیک کنید):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    logging.info(f"Callback received: {data}")

    # --- Preview button ---
    if data.startswith("preview_"):
        tid = data[8:]
        entry = DOWNLOAD_CACHE.get(tid)
        if entry and entry.get("preview"):
            await context.bot.send_voice(chat_id, voice=entry["preview"])
        return

    # --- Download button ---
    elif data.startswith("download_"):
        tid = data[9:]
        entry = DOWNLOAD_CACHE.get(tid)
        if not entry:
            await context.bot.send_message(chat_id, "❌ لینک دانلود موجود نیست.")
            return
        url = fetch_songlink_priority_url(entry["song_data"])
        if url:
            await context.bot.send_message(chat_id, "⬇️ در حال دانلود...")
            await download_and_send(update, context, url)
        else:
            await context.bot.send_message(chat_id, "❌ فایل قابل دانلود نیست.")
        return

    # --- Resolve song info ---
    elif data.startswith("resolve|"):
        sid = data.split("|", 1)[1]
        if chat_id not in SEARCH_CACHE or sid not in SEARCH_CACHE[chat_id]:
            await query.answer("⛔ لینک پیدا نشد.", show_alert=True)
            return

        url = SEARCH_CACHE[chat_id][sid]

        # Fetch song metadata
        song_data = fetch_songlink(url)
        if not song_data:
            await context.bot.send_message(chat_id, "⛔ خطا در ارتباط با Song.link")
            return

        # Extract iTunes metadata
        meta = extract_itunes(song_data)
        tid = str(uuid4())
        # Store both preview and song_data in cache
        DOWNLOAD_CACHE[tid] = {
            "song_data": song_data,
            "preview": meta.get("previewUrl") if meta else None
        }

        keyboard = []

        if meta:
            caption = format_meta(meta)
            # Preview button
            if meta.get("previewUrl"):
                keyboard.append([InlineKeyboardButton("🎧 پخش پیش‌نمایش", callback_data=f"preview_{tid}")])
            # Download button
            keyboard.append([InlineKeyboardButton("⬇️ دانلود آهنگ", callback_data=f"download_{tid}")])

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=meta.get("artworkUrl100", "").replace("100x100", "600x600"),
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        # Fallback if no metadata
        fallback_url = fetch_songlink_priority_url(song_data)
        if fallback_url:
            keyboard.append([InlineKeyboardButton("⬇️ دانلود آهنگ", callback_data=f"download_{tid}")])
            await context.bot.send_message(
                chat_id,
                "⚠️ اطلاعات کامل آهنگ موجود نیست، می‌توانید مستقیماً دانلود کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_message(chat_id, "❌ هیچ لینکی برای دانلود یافت نشد.")
