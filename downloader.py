# downloads.py
# ----------------------
import asyncio
import tempfile
import os
from uuid import uuid4
from io import BytesIO
import logging

from yt_dlp import YoutubeDL
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from PIL import Image
import piexif

logger = logging.getLogger("musicbot.downloads")

YTDL_DOWNLOAD_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192'
    }]
}

async def download_audio(url: str, ydl_opts: dict = None) -> str:
    """Download audio asynchronously using yt-dlp."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_audio_sync, url, ydl_opts or YTDL_DOWNLOAD_OPTS)

def download_audio_sync(url: str, ydl_opts: dict) -> str:
    """Synchronous download via yt-dlp."""
    tmp_dir = tempfile.gettempdir()
    out_template = os.path.join(tmp_dir, f"{uuid4()}.%(ext)s")
    opts = dict(ydl_opts, outtmpl=out_template)

    logger.info("Downloading: %s", url)
    with YoutubeDL(opts) as ydl:
        ydl.download([url])

    base = out_template.split('.%(ext)s')[0]
    for ext in ('mp3','m4a','webm','opus','wav','aac','flac'):
        path = f"{base}.{ext}"
        if os.path.exists(path):
            logger.info("Download completed: %s", path)
            return path

    # Fallback: search temp folder
    for f in os.listdir(tmp_dir):
        if f.startswith(os.path.basename(base)):
            path = os.path.join(tmp_dir, f)
            logger.info("Download found (fallback): %s", path)
            return path

    raise FileNotFoundError(f"Failed to download audio for {url}")

def embed_id3_tags(mp3_path: str, metadata: dict, cover_bytes: bytes = None):
    """Embed ID3 tags and optional cover art."""
    logger.info("Embedding ID3 tags to %s", mp3_path)
    try:
        try:
            tags = EasyID3(mp3_path)
        except ID3NoHeaderError:
            tags = EasyID3()
            tags.save(mp3_path)
        tags = EasyID3(mp3_path)

        title = metadata.get('trackName') or metadata.get('title')
        artist = metadata.get('artistName') or metadata.get('artist') or metadata.get('uploader')
        album = metadata.get('collectionName') or metadata.get('album')
        date = (metadata.get('releaseDate') or '')[:10]
        genre = metadata.get('primaryGenreName') or metadata.get('genre')

        if title: tags['title'] = title
        if artist: tags['artist'] = artist
        if album: tags['album'] = album
        if date: tags['date'] = date
        if genre: tags['genre'] = genre
        tags.save(mp3_path)

        if cover_bytes:
            audio = ID3(mp3_path)
            audio.delall('APIC')
            audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=cover_bytes))
            audio.save(mp3_path)
    except Exception:
        logger.exception("Failed to embed ID3 tags")

def edit_cover_exif(image_bytes: bytes, metadata: dict) -> bytes:
    """Edit EXIF metadata on cover image."""
    logger.info("Editing cover EXIF metadata")
    try:
        img = Image.open(BytesIO(image_bytes)).convert('RGB')
        out = BytesIO()
        exif_dict = {'0th': {}, 'Exif': {}, 'GPS': {}, '1st': {}, 'thumbnail': None}

        artist = metadata.get('artistName') or metadata.get('artist') or ''
        copyright_text = metadata.get('copyright') or ''
        desc = metadata.get('trackName') or metadata.get('title') or ''

        if artist: exif_dict['0th'][piexif.ImageIFD.Artist] = artist.encode('utf-16le')
        if copyright_text: exif_dict['0th'][piexif.ImageIFD.Copyright] = copyright_text.encode('utf-16le')
        if desc: exif_dict['0th'][piexif.ImageIFD.ImageDescription] = desc.encode('utf-16le')

        exif_bytes = piexif.dump(exif_dict)
        img.save(out, format='JPEG', exif=exif_bytes, quality=95)
        return out.getvalue()
    except Exception:
        logger.exception("Failed editing cover EXIF")
        return image_bytes
