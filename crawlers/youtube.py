from __future__ import annotations

import os
import sys
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger("yt_downloader")

# ── 320 kbps MP3 post‑processor ──────────────────────────────────────────
AUDIO_POSTPROCESSOR = {
    "key": "FFmpegExtractAudio",
    "preferredcodec": "mp3",
    "preferredquality": "192",
}

# ── Common yt‑dlp flags (shared by all methods) ──────────────────────────
COMMON_OPTS: dict = {
    "outtmpl": "%(title)s.%(ext)s",
    "noplaylist": True,
    "retries": 5,
    "fragment_retries": 5,
    "no_check_certificate": True,
    "concurrent_fragments": 8,
    "quiet": True,
    "no_warnings": True,
}

# ── User‑agent list ──────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


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


def _build_opts(method: int, output_dir: str) -> dict:
    """
    Build yt‑dlp options dict for the given method number (1‑8).
    Matches the 8 methods from the GitHub Actions workflow.
    """
    opts = dict(COMMON_OPTS)
    opts["outtmpl"] = f"{output_dir}/%(title)s.%(ext)s"
    opts["format"] = "bestaudio/best"
    opts["cookiefile"] = "cookies.txt"
    opts["postprocessors"] = [AUDIO_POSTPROCESSOR]

    has_deno = _check_deno()
    proxy = _check_proxy()

    # ── Method‑specific extractor args & proxy ────────────────────────
    if method == 8:
        # web client + deno + remote EJS (GitHub) + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]
        opts["http_headers"] = {
            "User-Agent": USER_AGENTS[0],
            "Accept-Language": "en-US,en;q=0.9",
        }

    elif method == 2:
        # web client + deno + remote EJS (npm fallback) + proxy
        if proxy:
            opts["proxy"] = proxy
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:npm"]
        opts["http_headers"] = {
            "User-Agent": USER_AGENTS[1],
            "Accept-Language": "en-US,en;q=0.9",
        }

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
        opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
            )
        }

    return opts


def download_audio(
        url: str,
        output_dir: Optional[str] = None,
        *,
        max_retries_per_method: int = 1,
) -> Optional[str]:  # 🔄 تغییر: حالا string برمی‌گرداند
    """
    Download YouTube audio as 320 kbps MP3.

    Tries all 8 anti‑detection methods in sequence. Returns the path
    to the downloaded MP3 file as a string, or None if every method failed.
    """
    url = _normalize_url(url)

    # استفاده از پوشه فعلی پروژه به جای temp
    if output_dir is None:
        # پوشه "downloads" در مسیر فعلی پروژه
        output_dir = os.path.join(os.getcwd(), "downloads")
    else:
        # اگر مسیر نسبی داده شده، آن را به مسیر مطلق در پروژه تبدیل کن
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.getcwd(), output_dir)
    
    # ایجاد پوشه اگر وجود نداشت
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Starting download: %s", url)
    logger.info("Output directory: %s", output_dir)
    logger.info("Deno available: %s | Proxy available: %s", _check_deno(), _check_proxy())

    # Remember what files existed before so we can identify the new MP3
    before = set(Path(output_dir).glob("*.mp3"))

    for method in range(1, 9):
        for attempt in range(1, max_retries_per_method + 1):
            logger.info("▶ Method %d, attempt %d", method, attempt)
            try:
                opts = _build_opts(method, output_dir)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except Exception as exc:
                logger.warning("Method %d failed: %s", method, exc)
                time.sleep(3)
                continue

            # Check whether a new MP3 appeared
            after = set(Path(output_dir).glob("*.mp3"))
            new_files = after - before
            if new_files:
                mp3_path = max(new_files, key=lambda p: p.stat().st_mtime)
                size_mb = mp3_path.stat().st_size / (1024 * 1024)
                logger.info("✅ Success with method %d → %s (%.1f MB)", method, mp3_path.name, size_mb)
                return str(mp3_path)  # 🔄 تبدیل Path به string
            else:
                logger.warning("Method %d completed but no MP3 found – retrying…", method)
                time.sleep(2)

    logger.error("❌ All 8 methods failed for: %s", url)
    return None


def _normalize_url(url: str) -> str:
    """Convert youtu.be short links to full youtube.com/watch?v= URLs."""
    import re
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if m:
        vid = m.group(1).split("?")[0]
        return f"https://www.youtube.com/watch?v={vid}"
    return url
