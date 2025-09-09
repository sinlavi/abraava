# ----------------------
# handler.py
# ----------------------
import logging
import os
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import SEARCH_CACHE, DOWNLOAD_LINKS_CACHE
from utils import is_valid_url, cb_make, cb_parse
from searcher import Searcher
from metadata import MetadataFetcher
from downloader import download_audio, embed_id3_tags, edit_cover_exif
from i18 import translate

logger = logging.getLogger("musicbot.handlers")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_lang = context.user_data.get("lang", "en")
    await update.message.reply_text(translate("start", user_lang))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_lang = context.user_data.get("lang", "en")
    query_text = (update.message.text or "").strip()

    if not query_text:
        await update.message.reply_text(translate("send_query", user_lang))
        return

    # URL case
    if is_valid_url(query_text):
        metadata = await MetadataFetcher.get_metadata(query_text)
        if not metadata:
            await update.message.reply_text(translate("error", user_lang))
            return

        track_id = str(uuid4())
        DOWNLOAD_LINKS_CACHE[track_id] = query_text

        buttons = [
            [InlineKeyboardButton("▶️ Preview", callback_data=cb_make("preview", track_id))],
            [InlineKeyboardButton("⬇️ Download", callback_data=cb_make("download", track_id))]
        ]

        await update.message.reply_text(
            f"🎶 {metadata.get('title', 'Unknown')} - {metadata.get('artistName', 'Unknown')}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Search case
    results = await Searcher.search(query_text, limit=5)
    if not results:
        await update.message.reply_text(translate("no_results", user_lang))
        return

    # Cache search results
    track_ids = []
    for result in results:
        track_id = str(uuid4())
        SEARCH_CACHE[track_id] = result
        track_ids.append(track_id)

    buttons = []
    for tid in track_ids:
        result = SEARCH_CACHE[tid]
        title = result.get("title") or result.get("trackName") or "Unknown"
        artist = result.get("uploader") or result.get("artistName") or ""
        buttons.append([InlineKeyboardButton(f"{title} - {artist}", callback_data=cb_make("select", tid))])

    await update.message.reply_text("🔍 Results:", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_lang = context.user_data.get("lang", "en")
    action, payload = cb_parse(query.data)

    if action == "select":
        result = SEARCH_CACHE.get(payload)
        if not result:
            await query.edit_message_text(translate("error", user_lang))
            return

        track_id = str(uuid4())
        DOWNLOAD_LINKS_CACHE[track_id] = result.get("url")

        buttons = [
            [InlineKeyboardButton("▶️ Preview", callback_data=cb_make("preview", track_id))],
            [InlineKeyboardButton("⬇️ Download", callback_data=cb_make("download", track_id))]
        ]
        title = result.get("title") or result.get("trackName") or "Unknown"
        artist = result.get("uploader") or result.get("artistName") or ""
        await query.edit_message_text(
            f"🎶 {title} - {artist}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif action == "download":
        url = DOWNLOAD_LINKS_CACHE.get(payload)
        if not url:
            await query.edit_message_text(translate("error", user_lang))
            return

        await query.edit_message_text(translate("downloading", user_lang))
        await worker_download_and_send(context, query.message.chat_id, url)

    elif action == "preview":
        url = DOWNLOAD_LINKS_CACHE.get(payload)
        if not url:
            await query.edit_message_text(translate("error", user_lang))
            return

        await context.bot.send_message(query.message.chat_id, f"🎧 Preview: {url}")

    else:
        await query.edit_message_text(translate("error", user_lang))


async def handle_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /setlang <language_code>")
        return

    lang_code = context.args[0].lower()
    supported_languages = ["en", "fa"]
    if lang_code not in supported_languages:
        await update.message.reply_text(f"Unsupported language. Supported: {', '.join(supported_languages)}")
        return

    context.user_data["lang"] = lang_code
    await update.message.reply_text(translate("start", lang_code))


async def worker_download_and_send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str):
    status_msg = await context.bot.send_message(chat_id, "⏳ Downloading...")

    try:
        mp3_path = await download_audio(url)
        metadata = await MetadataFetcher.get_metadata(url)

        cover_bytes = None
        if metadata and metadata.get("artworkUrl100"):
            # Resize or enhance artwork
            cover_url = metadata.get("artworkUrl100").replace("100x100", "600x600")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                cover_bytes_raw = await download_bytes(session, cover_url)
                if cover_bytes_raw:
                    cover_bytes = edit_cover_exif(cover_bytes_raw, metadata)

        embed_id3_tags(mp3_path, metadata or {}, cover_bytes)

        from telegram import InputFile
        with open(mp3_path, "rb") as fh:
            filename = f"{metadata.get('artistName', 'Unknown')} - {metadata.get('title', 'Unknown')}.mp3"
            await context.bot.send_audio(
                chat_id,
                audio=InputFile(fh, filename=filename),
                caption="✅ Download completed!"
            )

        await context.bot.delete_message(chat_id, status_msg.message_id)

    except Exception as e:
        logger.exception("Download/send failed")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text="❌ Failed")
    finally:
        if 'mp3_path' in locals() and os.path.exists(mp3_path):
            os.remove(mp3_path)


async def download_bytes(session, url: str) -> bytes:
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
    except Exception:
        logger.exception("Failed to fetch bytes from %s", url)
        return None


async def handle_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /setlang <language_code>")
        return

    lang_code = context.args[0].lower()
    supported_languages = ["en", "fa"]  # Add more supported languages as needed

    if lang_code not in supported_languages:
        await update.message.reply_text(f"Unsupported language. Supported languages: {', '.join(supported_languages)}")
        return

    context.user_data["lang"] = lang_code
    await update.message.reply_text(translate("start", lang_code))
