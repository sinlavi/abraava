# downloads.py
# ----------------------
import asyncio
import tempfile
import os
import random
from uuid import uuid4
from io import BytesIO
import logging
import json
import requests

from yt_dlp import YoutubeDL
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from PIL import Image
import piexif
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger("musicbot.downloads")

# ----------------------------
# CONFIG
# ----------------------------
YTDL_DOWNLOAD_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': False,
    'concurrent_fragment_downloads': 1,
    'retries': 10,
    'fragment_retries': 10,
    'socket_timeout': 20,
    'sleep_interval': 5,
    'max_sleep_interval': 12,
    'sleep_interval_requests': 3,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192'
    }],
}

DOWNLOAD_DIR = "downloads"
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
COOKIES_FILE = "cookies.txt"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------------------
# STEP 0: Generate token.json locally if missing
# ----------------------------
def generate_token_if_missing():
    if not os.path.exists(TOKEN_FILE):
        if not os.path.exists(CLIENT_SECRET_FILE):
            logger.error("client_secret.json not found!")
            raise FileNotFoundError("client_secret.json not found.")
        logger.info("token.json missing, starting local OAuth flow...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        logger.info("✅ token.json created. You can now use this in Actions.")

# ----------------------------
# STEP 1: Refresh cookies automatically
# ----------------------------
def refresh_youtube_cookies() -> bool:
    if not os.path.exists(TOKEN_FILE):
        logger.error("token.json missing, cannot refresh cookies")
        return False

    with open(TOKEN_FILE) as f:
        creds = json.load(f)

    refresh_token = creds.get("refresh_token")
    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")

    if not refresh_token or not client_id or not client_secret:
        logger.error("token.json missing required fields")
        return False

    token_url = "https://oauth2.googleapis.com/token"
    resp = requests.post(token_url, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        logger.error("Failed to refresh access token: %s", resp.text)
        return False

    access_token = resp.json().get("access_token")
    if not access_token:
        logger.error("No access token returned")
        return False

    # Write minimal cookies.txt for yt-dlp
    with open(COOKIES_FILE, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write(f".youtube.com\tTRUE\t/\tFALSE\t0\tSID\t{access_token}\n")

    logger.info("✅ cookies.txt refreshed successfully")
    return True

# ----------------------------
# STEP 2: Async download
# ----------------------------
async def download_audio(url: str, ydl_opts: dict = None) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_audio_sync, url, ydl_opts or YTDL_DOWNLOAD_OPTS)

def download_audio_sync(url: str, ydl_opts: dict) -> str:
    tmp_dir = tempfile.gettempdir()
    out_template = os.path.join(tmp_dir, f"{uuid4()}.%(ext)s")
    opts = dict(ydl_opts, outtmpl=out_template)
    opts['cookiefile'] = COOKIES_FILE

    logger.info("⬇️ Downloading %s", url)
    with YoutubeDL(opts) as ydl:
        ydl.download([url])

    base = out_template.split('.%(ext)s')[0]
    for ext in ('mp3','m4a','webm','opus','wav','aac','flac'):
        path = f"{base}.{ext}"
        if os.path.exists(path):
            logger.info("✅ Download completed: %s", path)
            return path

    # Fallback
    for f in os.listdir(tmp_dir):
        if f.startswith(os.path.basename(base)):
            path = os.path.join(tmp_dir, f)
            logger.info("✅ Download found (fallback): %s", path)
            return path

    raise FileNotFoundError(f"Failed to download audio for {url}")

# ----------------------------
# STEP 3: Embed metadata + cover
# ----------------------------
def embed_id3_tags(mp3_path: str, metadata: dict, cover_bytes: bytes = None):
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

        logger.info("✅ Metadata embedded for %s", mp3_path)
    except Exception:
        logger.exception("Failed to embed ID3 tags")

def edit_cover_exif(image_bytes: bytes, metadata: dict) -> bytes:
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

# ----------------------------
# STEP 4: Main entrypoint
# ----------------------------
async def download_with_metadata(url: str, metadata: dict, cover_bytes: bytes = None) -> str:
    if not refresh_youtube_cookies():
        raise RuntimeError("Cannot refresh cookies, aborting download")
    path = await download_audio(url)
    embed_id3_tags(path, metadata, cover_bytes)
    return path
