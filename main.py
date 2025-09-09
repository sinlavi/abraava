import os
import tempfile
import asyncio
import logging
from uuid import uuid4
from io import BytesIO

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
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read token from environment (e.g., GitHub secret BOT_TOKEN)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set")

# Caches
search_cache = TTLCache(maxsize=1000, ttl=3600)
download_links_cache = TTLCache(maxsize=1000, ttl=3600)

# YTDL options used for metadata extraction (no download)
YTDL_EXTRACT_OPTS = {"quiet": True, "extract_flat": True, "skip_download": True}


def format_song_info(metadata: dict) -> str:
    title = metadata.get("trackName") or metadata.get("title") or "Unknown Title"
    artist = metadata.get("artistName") or metadata.get("uploader") or "Unknown Artist"
    album = metadata.get("collectionName") or metadata.get("album") or "Unknown Album"
    release = (metadata.get("releaseDate") or "")[:10]
    genre = metadata.get("primaryGenreName") or metadata.get("genre") or "Unknown"
    text = (
        f"🎵 *{title}*\n"
        f"👤 *Artist:* {artist}\n"
        f"💿 *Album:* {album}\n"
        f"📅 *Released:* {release}\n"
        f"🎶 *Genre:* {genre}"
    )
    return text


async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None, timeout: int = 15):
    try:
        async with session.get(url, params=params, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.warning("HTTP fetch_json error: %s", e)
    return None


async def search_soundcloud(query: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_soundcloud_sync, query)


def _search_soundcloud_sync(query: str):
    try:
        with YoutubeDL(YTDL_EXTRACT_OPTS) as ydl:
            res = ydl.extract_info(f"scsearch5:{query}", download=False)
            return res.get("entries", [])[:5]
    except Exception as e:
        logger.warning("SoundCloud search error: %s", e)
        return []


async def search_itunes(query: str):
    async with aiohttp.ClientSession() as session:
        res = await fetch_json(session, "https://itunes.apple.com/search", params={"term": query, "media": "music", "limit": 5})
        return res.get("results", []) if res else []


async def fetch_songlink(url: str):
    async with aiohttp.ClientSession() as session:
        return await fetch_json(session, "https://api.song.link/v1-alpha.1/links", params={"url": url})


def extract_itunes_data(songlink_data: dict) -> dict:
    platforms = songlink_data.get("linksByPlatform", {}) or {}
    itunes = platforms.get("itunes", {}) or {}
    entity_id = itunes.get("entityUniqueId")
    return (songlink_data.get("entitiesByUniqueId", {}) or {}).get(entity_id, {})


def get_priority_download_url(songlink_data: dict) -> str | None:
    platforms = songlink_data.get("linksByPlatform", {}) or {}
    return (
        platforms.get("soundcloud", {}).get("url")
        or platforms.get("youtube", {}).get("url")
        or platforms.get("youtubeMusic", {}).get("url")
    )


async def download_media_to_temp(url: str, ydl_opts: dict) -> str:
    """
    Download using yt-dlp to a temporary file and return its path.
    This runs in a ThreadPoolExecutor because yt-dlp is blocking.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_media_sync, url, ydl_opts)


def _download_media_sync(url: str, ydl_opts: dict) -> str:
    tmpdir = tempfile.gettempdir()
    filename = os.path.join(tmpdir, f"{uuid4()}.%(ext)s")
    ydl_opts_copy = dict(ydl_opts)
    ydl_opts_copy["outtmpl"] = filename
    try:
        with YoutubeDL(ydl_opts_copy) as ydl:
            ydl.download([url])
        # find created file (yt-dlp will replace %(ext)s)
        base = filename.split(".%(ext)s")[0]
        # look for common extensions
        for ext in ("mp3", "m4a", "webm", "opus", "wav", "aac", "flac"):
            p = f"{base}.{ext}"
            if os.path.exists(p):
                return p
        # fallback: return any file starting with base
        for f in os.listdir(tmpdir):
            if f.startswith(os.path.basename(base)):
                return os.path.join(tmpdir, f)
    except Exception as e:
        logger.exception("yt-dlp download failed: %s", e)
        raise
    raise FileNotFoundError("Downloaded file not found")


def embed_id3_tags(mp3_path: str, metadata: dict, cover_bytes: bytes | None = None):
    """Set ID3 tags (Title, Artist, Album, Date, Genre) and embed cover art."""
    try:
        # Ensure EasyID3 exists or create tags
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

        if title:
            tags["title"] = title
        if artist:
            tags["artist"] = artist
        if album:
            tags["album"] = album
        if date:
            tags["date"] = date
        if genre:
            tags["genre"] = genre

        tags.save(mp3_path)

        # Embed cover art with ID3 APIC
        if cover_bytes:
            audio = ID3(mp3_path)
            audio.delall("APIC")
            audio.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover_bytes
                )
            )
            audio.save(mp3_path)
    except Exception:
        logger.exception("Failed to embed ID3 tags")


def edit_image_exif(image_bytes: bytes, metadata: dict) -> bytes:
    """
    Edit EXIF fields Artist, Copyright, ImageDescription.
    Returns new JPEG bytes. If input is PNG, convert to JPEG.
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        out_io = BytesIO()
        # Basic EXIF dict
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        artist = metadata.get("artistName") or metadata.get("artist") or ""
        copyright_text = metadata.get("copyright") or ""
        description = metadata.get("trackName") or metadata.get("title") or ""

        if artist:
            exif_dict["0th"][piexif.ImageIFD.Artist] = artist
        if copyright_text:
            exif_dict["0th"][piexif.ImageIFD.Copyright] = copyright_text
        if description:
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description

        exif_bytes = piexif.dump(exif_dict)
        img.save(out_io, format="JPEG", exif=exif_bytes, quality=95)
        return out_io.getvalue()
    except Exception:
        logger.exception("Failed to edit image EXIF")
        # Fallback: return original bytes
        return image_bytes


async def fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=20) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        logger.exception("Failed to fetch bytes")
    return None


async def send_song_details(context: ContextTypes.DEFAULT_TYPE, chat_id: int, metadata: dict, songlink_data: dict, reply_to_message_id: int | None = None):
    caption = format_song_info(metadata)
    artwork_url = (metadata.get("artworkUrl100") or "").replace("100x100", "600x600")
    download_id = str(uuid4())
    download_links_cache[download_id] = songlink_data

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search Again", callback_data="search_again")]
    ])

    # Add preview and download buttons conditionally
    preview_url = metadata.get("previewUrl")
    download_url = get_priority_download_url(songlink_data)
    buttons = []
    if preview_url:
        buttons.append(InlineKeyboardButton("🎧 Preview", callback_data=f"preview_{preview_url}"))
    if download_url:
        buttons.append(InlineKeyboardButton("⬇️ Download", callback_data=f"download_{download_id}"))
    if buttons:
        keyboard = InlineKeyboardMarkup([buttons, [InlineKeyboardButton("🔍 Search Again", callback_data="search_again")]])

    # Try to fetch artwork and attach edited EXIF if possible
    photo_bytes = None
    if artwork_url:
        async with aiohttp.ClientSession() as session:
            photo_bytes = await fetch_bytes(session, artwork_url)
            if photo_bytes:
                photo_bytes = edit_image_exif(photo_bytes, metadata)

    try:
        if photo_bytes:
            bio = BytesIO(photo_bytes)
            bio.name = "cover.jpg"
            await context.bot.send_photo(chat_id=chat_id, photo=InputFile(bio), caption=caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
    except Exception:
        logger.exception("Failed sending song details")
        await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown", reply_markup=keyboard, reply_to_message_id=reply_to_message_id)


async def download_and_send_audio(context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str, metadata: dict, reply_to_message_id: int | None = None):
    status = await context.bot.send_message(chat_id=chat_id, text="⏳ Downloading file...")
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "noplaylist": True,
        "postprocessors": [{ "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192" }],
    }

    try:
        # Download file to temp
        mp3_path = await download_media_to_temp(url, ydl_opts)

        # Fetch artwork bytes if available to embed
        cover_bytes = None
        artwork_url = (metadata.get("artworkUrl100") or "").replace("100x100", "600x600")
        if artwork_url:
            async with aiohttp.ClientSession() as session:
                cover_bytes = await fetch_bytes(session, artwork_url)

        # Embed ID3 tags and cover
        if mp3_path.lower().endswith(".mp3"):
            embed_id3_tags(mp3_path, metadata, cover_bytes)
        else:
            # If not mp3 (rare), try to convert/extract wasn't mp3 — still attempt tagging if mp3-like
            try:
                embed_id3_tags(mp3_path, metadata, cover_bytes)
            except Exception:
                pass

        # Send audio file
        with open(mp3_path, "rb") as f:
            await context.bot.send_audio(chat_id=chat_id, audio=InputFile(f, filename=os.path.basename(mp3_path)), caption="✅ Download completed!", reply_to_message_id=reply_to_message_id)

        await context.bot.delete_message(chat_id=chat_id, message_id=status.message_id)
    except Exception as e:
        logger.exception("Download/send failed")
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"❌ Download error: {e}")
        except Exception:
            pass
    finally:
        # Cleanup
        try:
            if 'mp3_path' in locals() and os.path.exists(mp3_path):
                os.remove(mp3_path)
        except Exception:
            logger.exception("Cleanup failed")


# Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send a song name to search.")


async def incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    if not text:
        await update.message.reply_text("🎵 Please send me a song name to search!")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    soundcloud_results, itunes_results = await asyncio.gather(search_soundcloud(text), search_itunes(text))
    all_results = (soundcloud_results or []) + (itunes_results or [])

    if not all_results:
        await update.message.reply_text("❌ No results found. Try a different search term.")
        return

    search_id = str(uuid4())
    search_cache[search_id] = {"results": all_results[:8], "timestamp": asyncio.get_event_loop().time(), "query": text}

    # Build keyboard
    buttons = []
    for idx, item in enumerate(all_results[:8], start=1):
        title = item.get("title") or item.get("trackName") or "Unknown Title"
        artist = item.get("uploader") or item.get("artistName") or "Unknown Artist"
        label = f"{idx}. {title[:30]} - {artist[:20]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"select_{search_id}_{idx-1}")])

    buttons.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(f"🔍 Found {len(all_results)} results for: *{text}*", parse_mode="Markdown", reply_markup=keyboard)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id
    message_id = query.message.message_id

    if data in ("new_search", "search_again"):
        await context.bot.send_message(chat_id=chat_id, text="🔍 Send me the name of the song you want to search:")
        return

    if data.startswith("preview_"):
        preview_url = data[len("preview_"):]
        # Telegram accepts URL voice by send_voice only with file_id or file - send as audio by URL via send_audio
        try:
            await context.bot.send_audio(chat_id=chat_id, audio=preview_url, reply_to_message_id=message_id)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="Unable to play preview.")
        return

    if data.startswith("download_"):
        download_id = data[len("download_"):]
        song_data = download_links_cache.get(download_id)
        if not song_data:
            await context.bot.send_message(chat_id=chat_id, text="❌ Download link expired. Please search again.")
            return
        download_url = get_priority_download_url(song_data)
        if download_url:
            # Try to extract metadata for tagging
            itunes_meta = extract_itunes_data(song_data) or {}
            # Launch background task
            context.application.create_task(download_and_send_audio(context, chat_id, download_url, itunes_meta, reply_to_message_id=message_id))
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ No download available for this track.")
        return

    if data.startswith("select_"):
        parts = data.split("_")
        if len(parts) != 3:
            return
        search_id = parts[1]
        try:
            result_index = int(parts[2])
        except ValueError:
            return
        search_data = search_cache.get(search_id)
        if not search_data:
            await context.bot.send_message(chat_id=chat_id, text="❌ Search results expired. Please search again.")
            return
        results = search_data["results"]
        if result_index >= len(results):
            await context.bot.send_message(chat_id=chat_id, text="❌ Invalid selection.")
            return
        selected_item = results[result_index]
        item_url = selected_item.get("webpage_url") or selected_item.get("trackViewUrl")
        if not item_url:
            await context.bot.send_message(chat_id=chat_id, text="❌ No URL available for this track.")
            return
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        songlink_data = await fetch_songlink(item_url)
        if not songlink_data:
            await context.bot.send_message(chat_id=chat_id, text="❌ Could not fetch track information.")
            return
        itunes_meta = extract_itunes_data(songlink_data)
        if itunes_meta:
            await send_song_details(context, chat_id, itunes_meta, songlink_data, reply_to_message_id=message_id)
        else:
            download_url = get_priority_download_url(songlink_data)
            if download_url:
                itunes_meta = {}
                context.application.create_task(download_and_send_audio(context, chat_id, download_url, itunes_meta, reply_to_message_id=message_id))
            else:
                await context.bot.send_message(chat_id=chat_id, text="❌ No download available for this track.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, incoming_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
