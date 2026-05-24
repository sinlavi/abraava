from __future__ import annotations

import difflib
import os
import sys
import time
import random
import logging
import subprocess
import tempfile
import uuid
import shutil
from pathlib import Path
from typing import Optional

import asyncio
import yt_dlp
from rapidfuzz import fuzz
from ytmusicapi import YTMusic

try:
    from config import OFFLINE_MODE
except ImportError:
    OFFLINE_MODE = False

logger = logging.getLogger("yt_downloader")
logging.basicConfig(level=logging.INFO)

# ── Audio post‑processor ──────────────────────────────────────────
AUDIO_POSTPROCESSOR = {
    "key": "FFmpegExtractAudio",
    "preferredcodec": "mp3",
    "preferredquality": "128",
}

# ── Common yt‑dlp flags (shared by all methods) ──────────────────────────
COMMON_OPTS: dict = {
    "outtmpl": "%(title)s.%(ext)s",
    "noplaylist": True,
    "retries": 10,
    "fragment_retries": 10,
    "no_check_certificate": True,
    "concurrent_fragments": 8,
    "quiet": True,
    "no_warnings": True,
    "sleep_interval": 2,  # تاخیر تصادفی برای جلوگیری از بلاک شدن
    "max_sleep_interval": 6,  # حداکثر تاخیر
    "sleep_interval_requests": 1,  # تاخیر بین درخواست‌های دیتا
}

# ── User‑agent list (Expanded for better bot evasion) ────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
]

# ── Smart Method Sorting ────────────────────────────────────────────────
# متدها بر اساس عملکردشان در طول زمان در این لیست جابجا می‌شوند
METHOD_ORDER = [8, 2, 3, 4, 5, 6, 7, 1]

# ============================================================================
# YouTube Music Helper
# ============================================================================
YT = None


# تابع کمکی برای محاسبه شباهت با rapidfuzz
def _get_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # استفاده از WRatio برای مدیریت بهتر غلط‌های املایی، حروف کوچک/بزرگ و جابه‌جایی کلمات
    return fuzz.WRatio(str(a), str(b)) / 100.0

def _sync_search_youtube(t_name: str, a_name: str, collection_name: str, ye: str) -> Optional[str]:
    global YT
    if YT is None:
        YT = YTMusic()

    # ساخت کوئری مناسب برای موتور جستجوی یوتیوب
    search_query = f"{t_name} {a_name} {collection_name}".strip()

    try:
        results = YT.search(search_query, filter="songs", limit=10)

        if not results or not isinstance(results, list):
            return None

        best_match_id = None
        highest_score = -1.0

        for res in results:
            # استخراج اطلاعات از نتیجه یوتیوب
            res_title = res.get("title", "")
            artists = res.get("artists", [])
            res_artist = ", ".join([a.get("name", "") for a in artists]) if artists else ""
            album_data = res.get("album") or {}
            res_album = album_data.get("name", "")
            res_year = res.get("year", "")

            score = 0.0

            # محاسبه امتیاز وزن‌دار با استفاده از پارامترهای ورودی و rapidfuzz
            # وزن‌دهی: نام ترک ۴۵٪، نام آرتیست ۳۵٪، نام آلبوم ۱۵٪
            score += _get_similarity(t_name, res_title) * 0.45
            score += _get_similarity(a_name, res_artist) * 0.35
            score += _get_similarity(collection_name, res_album) * 0.15

            # وزن سال ۵٪ (فقط در صورت وجود سال در ورودی و نتیجه)
            if ye and res_year:
                if str(ye) == str(res_year):
                    score += 0.05

            # ذخیره بهترین نتیجه
            if score > highest_score:
                highest_score = score
                best_match_id = res.get("videoId")

        return best_match_id

    except Exception as e:
        logger.error(f"YTMusic search error: {e}")

    return None
def get_artist_image(artist_name):
    global YT
    if YT is None:
        YT = YTMusic()
    try:
        search_results = YT.search(artist_name, filter="artists", limit=1)
    except Exception as e:
        logger.error(f"YTMusic search error: {e}")
        return None
    if search_results:
        # Get first artist result
        artist_id = search_results[0]['browseId']

        # Get artist details
        artist_info = YT.get_artist(artist_id)

        # Get the thumbnails
        if 'thumbnails' in artist_info:
            highest_quality = artist_info['thumbnails'][0]['url']
            return highest_quality

    return None


async def search_youtube_track(t_name, a_name, collection_name, ye) -> Optional[str]:
    if OFFLINE_MODE:
        logger.info("Offline mode: skipping YouTube search")
        return None
    return await asyncio.to_thread(_sync_search_youtube, t_name, a_name, collection_name, ye)


def _check_deno() -> bool:
    """Return True if Deno runtime is available."""
    try:
        subprocess.run(["deno", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _check_proxy() -> Optional[str]:
    """Return SOCKS5 proxy URL if WARP/Dante/etc. is listening on 1080."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        if s.connect_ex(("127.0.0.1", 1080)) == 0:
            s.close()
            return "socks5://127.0.0.1:1080"
    except Exception:
        pass
    finally:
        s.close()
    return None


def _get_random_headers() -> dict:
    """Generate professional browser headers to evade bot detection."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }


def _build_opts(method: int, output_dir: str, preferred_quality: int) -> dict:
    """
    Build yt‑dlp options dict for the given method number (1‑8).
    """
    opts = dict(COMMON_OPTS)
    opts["outtmpl"] = f"{output_dir}/%(title)s.%(ext)s"
    opts["format"] = "bestaudio/best"

    # استفاده از کوکی مرورگرها به جای فایل متنی ساده در صورت امکان
    # (اگر فایل وجود نداشت خطا نمی‌دهد، اما اگر باشد کمک زیادی به دور زدن می‌کند)
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"

    AUDIO_POSTPROCESSOR['preferredquality'] = str(preferred_quality)
    opts["postprocessors"] = [AUDIO_POSTPROCESSOR]

    has_deno = _check_deno()
    proxy = _check_proxy()

    opts["http_headers"] = _get_random_headers()

    # ── Method‑specific extractor args & proxy ────────────────────────
    if method == 8:
        # web client + deno + remote EJS (GitHub) + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 2:
        # web client + deno + remote EJS (npm fallback) + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:npm"]

    elif method == 3:
        # web + mweb + android_vr combined + deno + remote EJS + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {
            "youtube": {"player_client": ["web", "mweb", "android_vr"]}
        }
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 4:
        # mweb client + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif method == 5:
        # android_vr client + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}

    elif method == 6:
        # web client **no proxy** + deno + remote EJS
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 7:
        # mweb client **no proxy**
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif method == 1:
        # android client (last resort, may give lower quality)
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        opts["http_headers"]["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
        )

    return opts



async def download_audio(
        url: str,
        output_dir: Optional[str] = None,
        *,
        max_retries_per_method: int = 1,
        preferred_quality: int = 128,
) -> Optional[str]:
    """
    Download YouTube audio as MP3.
    """
    global METHOD_ORDER
    url = _normalize_url(url)

    if output_dir is None:
        base_dir = os.path.join(os.getcwd(), "downloads")
    else:
        base_dir = output_dir
    os.makedirs(base_dir, exist_ok=True)

    unique_id = uuid.uuid4().hex
    unique_dir = os.path.join(base_dir, unique_id)
    os.makedirs(unique_dir, exist_ok=True)

    logger.info("Starting download: %s", url)
    logger.info("Unique output directory: %s", unique_dir)

    before = set(Path(unique_dir).glob("*.mp3"))
    loop = asyncio.get_event_loop()  # گرفتن Event Loop

    for method in list(METHOD_ORDER):
        for attempt in range(1, max_retries_per_method + 1):
            logger.info("▶ Try Method %d (Attempt %d)", method, attempt)
            try:
                opts = _build_opts(method, unique_dir, preferred_quality)

                # رفع مشکل فریز شدن ربات: اجرای yt_dlp در ترد (Thread) جداگانه
                def run_ydl():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])

                await loop.run_in_executor(None, run_ydl)

            except Exception as exc:
                logger.warning("Method %d failed: %s", method, exc)
                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.append(method)

                # رفع مشکل فریز شدن: جایگزینی time.sleep با asyncio.sleep
                await asyncio.sleep(random.uniform(3.0, 6.0))
                continue

            after = set(Path(unique_dir).glob("*.mp3"))
            new_files = after - before
            if new_files:
                mp3_path = max(new_files, key=lambda p: p.stat().st_mtime)
                size_mb = mp3_path.stat().st_size / (1024 * 1024)
                logger.info("✅ Success with method %d → %s (%.1f MB)", method, mp3_path.name, size_mb)

                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.insert(0, method)

                return str(mp3_path)
            else:
                logger.warning("Method %d completed but no MP3 found – retrying…", method)
                # رفع مشکل فریز شدن: جایگزینی time.sleep با asyncio.sleep
                await asyncio.sleep(random.uniform(2.0, 4.0))

    try:
        shutil.rmtree(unique_dir, ignore_errors=True)
    except Exception:
        pass
    logger.error("❌ All methods failed for: %s", url)
    return None

def _normalize_url(url: str) -> str:
    """Convert youtu.be short links to full youtube.com/watch?v= URLs."""
    import re
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if m:
        vid = m.group(1).split("?")[0]
        return f"https://www.youtube.com/watch?v={vid}"
    return url
