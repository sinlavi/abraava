#!/usr/bin/env python3
"""
Telegram music search/download bot (single-file, structured, logging).

Features:
- Uses python-telegram-bot v20 (async).
- Reads BOT_TOKEN from env (suitable for GitHub Secrets).
- Searches SoundCloud (via yt-dlp) and iTunes (HTTP).
- Uses song.link to get platform links.
- Downloads audio with yt-dlp, converts to MP3, embeds ID3 tags and cover art.
- Edits artwork EXIF (Artist, Copyright, ImageDescription).
- Uses cached search results (cachetools TTLCache).
- Improved callback_data encoding/decoding and handling.
- Robust logging and error handling.
"""

import os
import sys
import tempfile
import asyncio
import logging
import json
import time
from uuid import uuid4
from io import BytesIO
import urllib.parse
from typing import Optional, Tuple, Dict, Any, List

import aiohttp
from yt_dlp import YoutubeDL
from cachetools import TTLCache
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
import piexif
from PIL import Image

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------
# Configuration & Setup
# ----------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("BOT_TOKEN environment variable not set", file=sys.stderr)
    sys.exit(1)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("music_bot")

# caches
SEARCH_CACHE = TTLCache(maxsize=1000, ttl=3600)
DOWNLOAD_LINKS_CACHE = TTLCache(maxsize=1000, ttl=3600)

# yt-dlp base options
YTDL_EXTRACT_OPTS = {"quiet": True, "extract_flat": True, "skip_download": True}
YTDL_DOWNLOAD_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192"
    }],
}

# ----------------------
# Utilities
# ----------------------
def cb_make(prefix: str, payload: str) -> str:
    """Create compact callback_data: prefix|payload"""
    # Ensure the total length doesn't exceed Telegram's 64-byte limit
    full_data = f"{prefix}|{payload}"
    if len(full_data) > 64:
        # If it's too long, truncate the payload
        max_payload_length = 64 - len(prefix) - 1  # -1 for the separator
        payload = payload[:max_payload_length]
    return f"{prefix}|{payload}"

def cb_parse(data: str) -> Tuple[str, str]:
    """Parse callback_data produced by cb_make"""
    if "|" not in data:
        return data, ""
    prefix, payload = data.split("|", 1)
    return prefix, payload

def safe_json_loads_text(content: str) -> Any:
    """Load JSON from text even if MIME type was nonstandard."""
    return json.loads(content)

# ----------------------
# HTTP helpers
# ----------------------
async def fetch_text(session: aiohttp.ClientSession, url: str, params: dict = None, timeout: int = 15) -> Optional[str]:
    """Fetch text and return it. Handles non-standard MIME types for JSON endpoints."""
    try:
        async with session.get(url, params=params, timeout=timeout) as resp:
            text = await resp.text()
            resp.raise_for_status()
            return text
    except aiohttp.ClientResponseError as e:
        # still return text when status=200 but non-JSON mime (rare), else log
        logger.warning("HTTP error fetching %s: %s", url, e)
    except Exception as e:
        logger.exception("fetch_text failed for %s: %s", url, e)
    return None

async def fetch_json_forced(session: aiohttp.ClientSession, url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    """
    Fetch JSON, but be tolerant of non-JSON content-types.
    This fixes the iTunes warning: iTunes sometimes returns text/javascript as MIME.
    """
    text = await fetch_text(session, url, params=params, timeout=timeout)
    if not text:
        return None
    try:
        return safe_json_loads_text(text)
    except Exception as e:
        logger.exception("JSON parse failed for %s: %s -- raw length=%d", url, e, len(text))
        return None

async def fetch_bytes(session: aiohttp.ClientSession, url: str, timeout: int = 20) -> Optional[bytes]:
    try:
        async with session.get(url, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()
    except Exception as e:
        logger.warning("Failed to fetch bytes from %s: %s", url, e)
    return None

# ----------------------
# Search & metadata
# ----------------------
def search_soundcloud_sync(query: str) -> List[dict]:
    try:
        with YoutubeDL(YTDL_EXTRACT_OPTS) as ydl:
            res = ydl.extract_info(f"scsearch5:{query}", download=False)
            entries = res.get("entries", []) if res else []
            logger.debug("soundcloud search returned %d entries for query=%s", len(entries), query)
            return entries[:5]
    except Exception as e:
        logger.exception("SoundCloud search failed: %s", e)
        return []

async def search_soundcloud(query: str) -> List[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_soundcloud_sync, query)

async def search_itunes(query: str) -> List[dict]:
    async with aiohttp.ClientSession() as session:
        data = await fetch_json_forced(session, "https://itunes.apple.com/search", params={"term": query, "media": "music", "limit": 5})
        if not data:
            return []
        results = data.get("results", [])
        logger.debug("itunes search returned %d for query=%s", len(results), query)
        return results

async def fetch_songlink(url: str) -> Optional[dict]:
    async with aiohttp.ClientSession() as session:
        return await fetch_json_forced(session, "https://api.song.link/v1-alpha.1/links", params={"url": url})

def extract_itunes_data(songlink_data: dict) -> dict:
    if not songlink_data:
        return {}
    platforms = songlink_data.get("linksByPlatform", {}) or {}
    itunes = platforms.get("itunes", {}) or {}
    entity_id = itunes.get("entityUniqueId")
    return (songlink_data.get("entitiesByUniqueId", {}) or {}).get(entity_id, {}) or {}

def get_priority_download_url(songlink_data: dict) -> Optional[str]:
    if not songlink_data:
        return None
    platforms = songlink_data.get("linksByPlatform", {}) or {}
    return (platforms.get("soundcloud") or {}).get("url") or (platforms.get("youtube") or {}).get("url") or (platforms.get("youtubeMusic") or {}).get("url")

def format_song_info(metadata: dict) -> str:
    title = metadata.get("trackName") or metadata.get("title") or "Unknown Title"
    artist = metadata.get("artistName") or metadata.get("uploader") or "Unknown Artist"
    album = metadata.get("collectionName") or metadata.get("album") or "Unknown Album"
    release = (metadata.get("releaseDate") or "")[:10]
    genre = metadata.get("primaryGenreName") or metadata.get("genre") or "Unknown"
    return (
        f"🎵 *{title}*\n"
        f"👤 *Artist:* {artist}\n"
        f"💿 *Album:* {album}\n"
        f"📅 *Released:* {release}\n"
        f"🎶 *Genre:* {genre}"
    )

# ----------------------
# Download & tagging
# ----------------------
def download_media_sync(url: str, ydl_opts: dict) -> str:
    tmp = tempfile.gettempdir()
    base = os.path.join(tmp, f"{uuid4()}.%(ext)s")
    opts = dict(ydl_opts)
    opts["outtmpl"] = base
    logger.info("Starting yt-dlp download: %s", url)
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    prefix = base.split(".%(ext)s")[0]
    # look for common extensions
    for ext in ("mp3", "m4a", "webm", "opus", "wav", "aac", "flac"):
        p = f"{prefix}.{ext}"
        if os.path.exists(p):
            logger.info("Downloaded file found: %s", p)
            return p
    # fallback: any file with prefix
    for f in os.listdir(tempfile.gettempdir()):
        if f.startswith(os.path.basename(prefix)):
            p = os.path.join(tempfile.gettempdir(), f)
            logger.info("Downloaded file (fallback) found: %s", p)
            return p
    logger.error("Download produced no file for prefix=%s", prefix)
    raise FileNotFoundError("Download failed")

async def download_media(url: str, ydl_opts: dict) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_media_sync, url, ydl_opts)

def embed_id3(mp3_path: str, metadata: dict, cover_bytes: Optional[bytes]):
    logger.info("Embedding ID3 tags to %s", mp3_path)
    try:
        try:
            tags = EasyID3(mp3_path)
        except ID3NoHeaderError:
            tags = EasyID3()
            tags.save(mp3_path)
        tags = EasyID3(mp3_path)
        title = metadata.get("trackName") or metadata.get("title")
        artist = metadata.get("artistName") or metadata.get("artist") or metadata.get("uploader")
        album = metadata.get("collectionName") or metadata.get("album")
        date = (metadata.get("releaseDate") or "")[:10]
        genre = metadata.get("primaryGenreName") or metadata.get("genre")
        if title: tags["title"] = title
        if artist: tags["artist"] = artist
        if album: tags["album"] = album
        if date: tags["date"] = date
        if genre: tags["genre"] = genre
        tags.save(mp3_path)
        if cover_bytes:
            audio = ID3(mp3_path)
            audio.delall("APIC")
            audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes))
            audio.save(mp3_path)
        logger.debug("ID3 embedding done for %s", mp3_path)
    except Exception:
        logger.exception("Failed embedding ID3")

def edit_image_exif(image_bytes: bytes, metadata: dict) -> bytes:
    logger.info("Editing EXIF metadata on image")
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        out = BytesIO()
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        artist = metadata.get("artistName") or metadata.get("artist") or ""
        copyright_text = metadata.get("copyright") or ""
        desc = metadata.get("trackName") or metadata.get("title") or ""
        if artist:
            exif_dict["0th"][piexif.ImageIFD.Artist] = artist
        if copyright_text:
            exif_dict["0th"][piexif.ImageIFD.Copyright] = copyright_text
        if desc:
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = desc
        exif_bytes = piexif.dump(exif_dict)
        img.save(out, format="JPEG", exif=exif_bytes, quality=95)
        return out.getvalue()
    except Exception:
        logger.exception("edit_image_exif failed")
        return image_bytes

# ----------------------
# Telegram handlers
# ----------------------
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("Start invoked by user=%s id=%s", user.full_name if user else None, user.id if user else None)
    await update.message.reply_text("Hello — send a song name to search.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    logger.info("Message from user=%s id=%s text=%s", user.full_name if user else None, user.id if user else None, text)
    if not text:
        await update.message.reply_text("Send a song name.")
        return

    # Typing...
    await context.bot.send_chat_action(chat_id, action=constants.ChatAction.TYPING)

    # Run searches in parallel
    soundcloud_task = asyncio.create_task(search_soundcloud(text))
    itunes_task = asyncio.create_task(search_itunes(text))
    soundcloud_results, itunes_results = await asyncio.gather(soundcloud_task, itunes_task)
    combined = (soundcloud_results or []) + (itunes_results or [])
    if not combined:
        await update.message.reply_text("No results found.")
        logger.info("No search results for query=%s", text)
        return

    # Cache
    search_id = str(uuid4())
    SEARCH_CACHE[search_id] = {"results": combined[:8], "timestamp": time.time(), "query": text}
    logger.info("Cached search_id=%s for query=%s results=%d", search_id, text, len(combined))

    # Build keyboard
    buttons = []
    for idx, item in enumerate(combined[:8], start=1):
        title = item.get("title") or item.get("trackName") or "Unknown Title"
        artist = item.get("uploader") or item.get("artistName") or "Unknown Artist"
        label = f"{idx}. {title[:30]} - {artist[:20]}"
        # Use index only in callback data to avoid exceeding Telegram's 64-byte limit
        payload = f"{search_id}:{idx-1}"
        buttons.append([InlineKeyboardButton(label, callback_data=cb_make("select", payload))])
    buttons.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(f"Found {len(combined)} results for *{text}*", parse_mode="Markdown", reply_markup=keyboard)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    prefix, payload = cb_parse(query.data)
    user = query.from_user
    chat_id = query.message.chat.id
    msg_id = query.message.message_id
    logger.info("Callback from user=%s prefix=%s payload=%s", user.id if user else None, prefix, payload)

    if prefix in ("new_search", "search_again"):
        await context.bot.send_message(chat_id, "Send a new search query.")
        return

    if prefix == "preview":
        preview_url = payload
        logger.info("Preview requested: %s", preview_url)
        try:
            await context.bot.send_audio(chat_id, audio=preview_url, reply_to_message_id=msg_id)
        except Exception:
            logger.exception("Failed to send preview")
            await context.bot.send_message(chat_id, "Unable to play preview.")
        return

    if prefix == "download":
        download_id = payload
        logger.info("Download requested download_id=%s", download_id)
        songlink_data = DOWNLOAD_LINKS_CACHE.get(download_id)
        if not songlink_data:
            await context.bot.send_message(chat_id, "Download expired. Search again.")
            return
        dl_url = get_priority_download_url(songlink_data)
        if not dl_url:
            await context.bot.send_message(chat_id, "No download available.")
            return
        itunes_meta = extract_itunes_data(songlink_data) or {}
        # Launch background task
        context.application.create_task(worker_download_and_send(context, chat_id, dl_url, itunes_meta, msg_id))
        return

    if prefix == "select":
        # payload encoded as "search_id:idx"
        if ":" not in payload:
            logger.warning("Malformed select payload=%s", payload)
            return
        search_id, idx_str = payload.split(":", 1)
        try:
            idx = int(idx_str)
        except ValueError:
            logger.warning("Invalid index in payload=%s", payload)
            return
        search_data = SEARCH_CACHE.get(search_id)
        if not search_data:
            await context.bot.send_message(chat_id, "Search expired. Start a new search.")
            return
        results = search_data["results"]
        if idx >= len(results):
            await context.bot.send_message(chat_id, "Invalid selection.")
            return
        item = results[idx]
        item_url = item.get("webpage_url") or item.get("trackViewUrl")
        if not item_url:
            await context.bot.send_message(chat_id, "No URL found for this track.")
            return
        await context.bot.send_chat_action(chat_id, action=constants.ChatAction.TYPING)
        songlink_data = await fetch_songlink(item_url)
        if not songlink_data:
            await context.bot.send_message(chat_id, "Failed to fetch track info.")
            return
        itunes_meta = extract_itunes_data(songlink_data)
        if itunes_meta:
            # store download link in cache for later
            dl_id = str(uuid4())
            DOWNLOAD_LINKS_CACHE[dl_id] = songlink_data
            # send song details with buttons referencing dl_id
            await send_song_details(context, chat_id, itunes_meta, songlink_data, reply_to_message_id=msg_id)
        else:
            dl_url = get_priority_download_url(songlink_data)
            if dl_url:
                context.application.create_task(worker_download_and_send(context, chat_id, dl_url, {}, msg_id))
            else:
                await context.bot.send_message(chat_id, "No download available for this track.")

# Helper to send song info and buttons
async def send_song_details(context: ContextTypes.DEFAULT_TYPE, chat_id: int, metadata: dict, songlink_data: dict, reply_to_message_id: Optional[int] = None):
    caption = format_song_info(metadata)
    artwork = (metadata.get("artworkUrl100") or "").replace("100x100", "600x600")
    download_id = str(uuid4())
    DOWNLOAD_LINKS_CACHE[download_id] = songlink_data
    preview = metadata.get("previewUrl")
    download_url = get_priority_download_url(songlink_data)

    buttons_row = []
    if preview:
        # Use a short callback data for preview
        buttons_row.append(InlineKeyboardButton("🎧 Preview", callback_data=cb_make("preview", preview)))
    if download_url:
        # Use a UUID for download callback to keep it short
        buttons_row.append(InlineKeyboardButton("⬇️ Download", callback_data=cb_make("download", download_id)))
    buttons_row.append(InlineKeyboardButton("🔍 Search Again", callback_data="search_again"))
    keyboard = InlineKeyboardMarkup([buttons_row])

    photo_bytes = None
    if artwork:
        async with aiohttp.ClientSession() as session:
            tmp = await fetch_bytes(session, artwork)
            if tmp:
                photo_bytes = edit_image_exif(tmp, metadata)

    try:
        if photo_bytes:
            bio = BytesIO(photo_bytes); bio.name = "cover.jpg"
            await context.bot.send_photo(chat_id, photo=InputFile(bio), caption=caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
        else:
            await context.bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
        logger.info("Sent song details to chat_id=%s", chat_id)
    except Exception:
        logger.exception("Failed to send song details")
        await context.bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)

# Worker that downloads, tags, and sends audio (background)
async def worker_download_and_send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str, metadata: dict, reply_to_message_id: Optional[int] = None):
    logger.info("Background download task started for chat=%s url=%s", chat_id, url)
    status_msg = await context.bot.send_message(chat_id, "⏳ Downloading...")
    mp3_path = None
    try:
        mp3_path = await download_media(url, YTDL_DOWNLOAD_OPTS)
        # fetch cover if possible
        cover_bytes = None
        art = (metadata.get("artworkUrl100") or "").replace("100x100", "600x600")
        if art:
            async with aiohttp.ClientSession() as session:
                cover_bytes = await fetch_bytes(session, art)
        if mp3_path.lower().endswith(".mp3"):
            embed_id3(mp3_path, metadata, cover_bytes)
        else:
            # still try to tag if possible
            try:
                embed_id3(mp3_path, metadata, cover_bytes)
            except Exception:
                logger.debug("Skipping ID3 embed for non-mp3 file %s", mp3_path)
        # send audio
        with open(mp3_path, "rb") as fh:
            await context.bot.send_audio(chat_id, audio=InputFile(fh, filename=os.path.basename(mp3_path)), caption="✅ Download completed!", reply_to_message_id=reply_to_message_id)
        await context.bot.delete_message(chat_id, status_msg.message_id)
        logger.info("Sent audio to chat_id=%s", chat_id)
    except Exception as e:
        logger.exception("Download/send failed: %s", e)
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=f"❌ Error: {e}")
        except Exception:
            logger.exception("Failed updating error message")
    finally:
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
                logger.debug("Removed temp file %s", mp3_path)
            except Exception:
                logger.exception("Failed to remove temp file %s", mp3_path)

# ----------------------
# Main
# ----------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Starting bot polling")
    app.run_polling()

if __name__ == "__main__":
    main()