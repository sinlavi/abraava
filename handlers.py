import logging
import os
import re
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, MessageEntity
from telegram.ext import ContextTypes
from utils import extract_url, cb_make, cb_parse, convert_results_to_buttons
from crawler import Crawler
from downloader import download_audio, embed_id3_tags, edit_cover_exif
from i18n import translate
import httpx

logger = logging.getLogger("abraava.handlers")


# ----------------- Pagination Buttons -----------------
def build_pagination_buttons(results, query, page, platform):
    buttons = convert_results_to_buttons(results)

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️ Previous",
            callback_data=cb_make("page", f"{platform}:{query}:{page - 1}")
        ))

    nav_buttons.append(InlineKeyboardButton(
        "➡️ Next",
        callback_data=cb_make("page", f"{platform}:{query}:{page + 1}")
    ))

    buttons.append(nav_buttons)
    return InlineKeyboardMarkup(buttons)


# ----------------- Song Info Helper -----------------
async def send_song_info(context: ContextTypes.DEFAULT_TYPE, chat_id: int, track_id_or_url: str):
    try:
        metadata = await Crawler.extract_metadata(track_id_or_url)

        if not metadata:
            await context.bot.send_message(chat_id, translate("error", context=context))
            return

        buttons = [
            [InlineKeyboardButton("⬇️ Download", callback_data=cb_make("download", track_id_or_url))]
        ]
        if "previewUrl" in metadata:
            buttons.append(
                [InlineKeyboardButton("▶️ Preview", callback_data=cb_make("preview", metadata["previewUrl"]))]
            )
        if metadata.get("coverUrl"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=metadata["coverUrl"],
                caption=f"""
🎧 Title: <code>{metadata.get("title", "Unknown")}</code>
🎤 Artist: <code>{metadata.get("artist", "Unknown")}</code>
💽 Album: <code>{metadata.get("album", "Unknown")}</code>
🗓 Release Year: <code>{metadata.get("releaseDate", "Unknown")}</code>
🌐 ISRC: {metadata.get("isrc", "Unknown")}

🔗 Link: {track_id_or_url}
""",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"""
🎧 {metadata.get("title", "Unknown")}
🎤 {metadata.get("artist", "Unknown")}
💽 {metadata.get("album", "Unknown")}
🗓 {metadata.get("releaseDate", "Unknown")}
🌐 ISRC: {metadata.get("isrc", "")}
""",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
    except Exception as e:
        logger.exception("send_song_info failed")
        await context.bot.send_message(chat_id, translate("error", context=context))


# ----------------- Generic Search Handler -----------------
async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE, platform: str):
    message = update.message
    text = message.text.split(maxsplit=1)
    query = text[1] if len(text) > 1 else ""
    if not query:
        await message.reply_text(translate("send_query", context=context))
        return

    page = 1

    if platform == "itunes":
        results = await Crawler.Itunes.search(query, page=page)
    elif platform == "spotify":
        results = await Crawler.Spotify.search(query, page=page)
    elif platform == "deezer":
        results = await Crawler.Deezer.search(query, page=page)
    elif platform == "scloud":
        results = await Crawler.SoundCloud.search(query, page=page)
    elif platform == "ytmusic":
        results = await Crawler.YTMusic.search(query, page=page)
    else:
        results = []

    if not results:
        await message.reply_text(translate("no_results", context=context))
        return

    buttons = build_pagination_buttons(results, query, page, platform)
    await message.reply_text(
        translate(f'search.{platform}', context=context),
        reply_markup=buttons
    )


# ----------------- Individual Search Wrappers -----------------
async def handle_itunes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_search(update, context, "itunes")


async def handle_spotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_search(update, context, "spotify")


async def handle_deezer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_search(update, context, "deezer")


async def handle_scloud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_search(update, context, "scloud")


async def handle_ytmusic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_search(update, context, "ytmusic")


# ----------------- Start / Setting -----------------
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(translate("start", context=context))


async def handle_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(translate("start", context=context))


# ----------------- Message Handler -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = (message.text or "").strip()

    if not text:
        await message.reply_text(translate("send_query", context=context), parse_mode="Markdown")
        return
    url = False
    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntity.URL:
                url = message.text[entity.offset: entity.offset + entity.length]
            elif entity.type == MessageEntity.TEXT_LINK:
                url = entity.url
    match = re.search(r"(https?://[^\s]+)", message.text or False)
    if match:
        url = match.group(0)
    if url:
        await send_song_info(context, message.chat_id, url)
        return

    results = await Crawler.search_all(text)
    if not results:
        await update.message.reply_text(translate("no_results", context=context))
        return

    buttons = convert_results_to_buttons(results)
    await update.message.reply_text("🔍 Results:", reply_markup=InlineKeyboardMarkup(buttons))


# ----------------- Callback Handler -----------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    action, payload = cb_parse(query.data)

    if action == "page":
        platform, query_text, page_str = payload.split(":", 2)
        page = int(page_str)

        if platform == "itunes":
            results = await Crawler.Itunes.search(query_text, page=page)
        elif platform == "spotify":
            results = await Crawler.Spotify.search(query_text, page=page)
        elif platform == "deezer":
            results = await Crawler.Deezer.search(query_text, page=page)
        elif platform == "scloud":
            results = await Crawler.SoundCloud.search(query_text, page=page)
        elif platform == "ytmusic":
            results = await Crawler.YTMusic.search(query_text, page=page)
        else:
            await query.edit_message_text("❌ Unknown platform")
            return

        buttons = build_pagination_buttons(results, query_text, page, platform)
        await query.edit_message_text(
            translate(f'search.{platform}', context=context),
            reply_markup=buttons
        )

    elif action == "info":
        if not payload:
            await query.edit_message_text(translate("error", context=context))
            return
        await send_song_info(context, query.from_user.id, payload)

    elif action == "download":
        await query.edit_message_text(translate("downloading", context=context))
        await worker_download_and_send(context, query.message.chat_id, payload)

    elif action == "preview":
        await context.bot.send_audio(query.message.chat_id, audio=payload)

    else:
        await query.edit_message_text(translate("error", context=context))


# ----------------- Download Worker -----------------
async def worker_download_and_send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str):
    status_msg = await context.bot.send_message(chat_id, "⏳ Downloading...")

    try:
        mp3_path = await download_audio(url)
        metadata = await Crawler.extract_metadata(url)

        cover_bytes = None
        if metadata and metadata.get("artworkUrl100"):
            cover_url = metadata.get("artworkUrl100").replace("100x100", "600x600")
            async with httpx.AsyncClient() as client:
                response = await client.get(cover_url)
                if response.status_code == 200:
                    cover_bytes = edit_cover_exif(response.content, metadata)

        embed_id3_tags(mp3_path, metadata or {}, cover_bytes)

        with open(mp3_path, "rb") as fh:
            filename = f"{metadata.get('artistName', 'Unknown')} - {metadata.get('title', 'Unknown')}.mp3"
            await context.bot.send_audio(
                chat_id,
                audio=InputFile(fh, filename=filename),
                caption="✅ Download completed!"
            )

        await context.bot.delete_message(chat_id, status_msg.message_id)

    except Exception:
        logger.exception("Download/send failed")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text="❌ Failed")
    finally:
        if 'mp3_path' in locals() and os.path.exists(mp3_path):
            os.remove(mp3_path)


# ----------------- Language Setting -----------------
async def handle_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setlang <language_code>")
        return

    lang_code = context.args[0].lower()
    supported_languages = ["en", "fa"]

    if lang_code not in supported_languages:
        await update.message.reply_text(f"Unsupported language. Supported languages: {', '.join(supported_languages)}")
        return

    context.user_data["lang"] = lang_code
    await update.message.reply_text(translate("start", lang_code))
