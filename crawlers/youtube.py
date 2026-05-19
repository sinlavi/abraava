from __future__ import annotations

import os
import sys
import time
import random
import logging
import subprocess
from pathlib import Path
from typing import Optional

import asyncio
import yt_dlp
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


def _sync_search_youtube(query: str) -> Optional[str]:
    global YT
    if YT is None:
        YT = YTMusic()
    try:
        results = YT.search(query, filter="songs", limit=1)
        if results and isinstance(results, list) and len(results) > 0:
            return results[0].get("videoId")
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
            thumbnails = artist_info['thumbnails']
            highest_quality = thumbnails[-1]['url']
            return highest_quality

    return None


async def search_youtube_track(query: str) -> Optional[str]:
    if OFFLINE_MODE:
        logger.info("Offline mode: skipping YouTube search")
        return None
    return await asyncio.to_thread(_sync_search_youtube, query)


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


def download_audio(
        url: str,
        output_dir: Optional[str] = None,
        *,
        max_retries_per_method: int = 1,
        preferred_quality: int = 128,
) -> Optional[str]:
    """
    Download YouTube audio as "your entered" kbps MP3.
    Smartly sorts methods based on success rate and evades bot detection.
    """
    global METHOD_ORDER
    url = _normalize_url(url)

    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "downloads")
    else:
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.getcwd(), output_dir)

    os.makedirs(output_dir, exist_ok=True)

    logger.info("Starting download: %s", url)
    logger.info("Output directory: %s", output_dir)
    logger.info("Deno available: %s | Proxy available: %s", _check_deno(), _check_proxy())
    logger.info("Current method priority: %s", METHOD_ORDER)

    before = set(Path(output_dir).glob("*.mp3"))

    for method in list(METHOD_ORDER):  # Copy list to iterate
        for attempt in range(1, max_retries_per_method + 1):
            logger.info("▶ Try Method %d (Attempt %d)", method, attempt)
            try:
                opts = _build_opts(method, output_dir, preferred_quality)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except Exception as exc:
                logger.warning("Method %d failed: %s", method, exc)
                # در صورت شکست، متد فعلی را به انتهای لیست می‌فرستیم
                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.append(method)
                time.sleep(random.uniform(3.0, 6.0))
                continue

            after = set(Path(output_dir).glob("*.mp3"))
            new_files = after - before
            if new_files:
                mp3_path = max(new_files, key=lambda p: p.stat().st_mtime)
                size_mb = mp3_path.stat().st_size / (1024 * 1024)
                logger.info("✅ Success with method %d → %s (%.1f MB)", method, mp3_path.name, size_mb)

                # بهینه‌سازی هوشمند: متد موفق به صدر لیست می‌آید
                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.insert(0, method)

                return str(mp3_path)
            else:
                logger.warning("Method %d completed but no MP3 found – retrying…", method)
                time.sleep(random.uniform(2.0, 4.0))

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
