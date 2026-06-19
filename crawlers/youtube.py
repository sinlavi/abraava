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
    from core.config import OFFLINE_MODE, PROXY
except ImportError:
    OFFLINE_MODE = False
    PROXY = None

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
    "sleep_interval": 2,
    "max_sleep_interval": 6,
    "sleep_interval_requests": 1,
}

YT: Optional[YTMusic] = None
METHOD_ORDER = [1, 2, 3, 4, 5, 6, 7, 8]
SEARCH_METHOD_ORDER = ["ytmusic", "youtube"]

def _get_cookies_path() -> Optional[str]:
    cookies_txt = os.path.join(os.getcwd(), "cookies.txt")
    if os.path.exists(cookies_txt):
        return cookies_txt
    return None

def _get_random_headers() -> dict:
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

def _check_deno() -> bool:
    try:
        subprocess.run(["deno", "--version"], capture_output=True, check=True)
        return True
    except:
        return False

async def search_youtube_track(t_name: str, a_name: str, collection_name: str, ye: str, target_duration_ms: int = 0) -> Optional[str]:
    if OFFLINE_MODE: return None
    
    successful_methods = []
    best_result = None
    best_score = -1.0
    best_title_sim = 0.0

    for method in list(SEARCH_METHOD_ORDER):
        try:
            if method == "ytmusic":
                res_id = _sync_search_youtube(t_name, a_name, collection_name, ye, target_duration_ms)
                if res_id:
                    successful_methods.append(method)
                    return res_id

            # YouTube search could be added here if needed
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            logger.debug(f"Search method {method} error: {e}")
    
    return None

def _get_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.WRatio(str(a), str(b)) / 100.0

def _sync_search_youtube(t_name: str, a_name: str, collection_name: str, ye: str, target_duration_ms: int = 0) -> Optional[str]:
    global YT
    if YT is None:
        proxies = {"https": PROXY, "http": PROXY} if PROXY else None
        YT = YTMusic(proxies=proxies)

    search_query = f"{t_name} {a_name} {collection_name}".strip()

    try:
        results = YT.search(search_query, filter="songs", limit=10)
        if not results or not isinstance(results, list): return None

        best_match_id = None
        highest_score = -1.0
        best_title_sim = 0.0

        for res in results:
            res_title = res.get("title", "")
            artists = res.get("artists", [])
            res_artist = ", ".join([a.get("name", "") for a in artists]) if artists else ""
            album_data = res.get("album") or {}
            res_album = album_data.get("name", "")
            res_year = res.get("year", "")
            duration_sec = res.get("duration_seconds", 0)

            score = 0.0
            title_sim = _get_similarity(t_name, res_title)
            score += title_sim * 0.40
            score += _get_similarity(a_name, res_artist) * 0.30

            if target_duration_ms > 0 and duration_sec > 0:
                target_sec = target_duration_ms / 1000
                diff = abs(target_sec - duration_sec)
                if diff < 5: score += 0.20
                elif diff < 15: score += 0.10
                elif diff > 30: score -= 0.50

            score += _get_similarity(collection_name, res_album) * 0.05
            if ye and res_year and str(ye) == str(res_year): score += 0.05

            if score > highest_score:
                highest_score = score
                best_match_id = res.get("videoId")
                best_title_sim = title_sim

        if best_match_id:
            if highest_score < 0.45 or best_title_sim < 0.4:
                return None

        return best_match_id
    except Exception as e:
        logger.error(f"YTMusic search error: {e}")
    return None

def get_artist_image(artist_name):
    global YT
    if YT is None:
        try:
            proxies = {"https": PROXY, "http": PROXY} if PROXY else None
            YT = YTMusic(proxies=proxies)
        except Exception as e:
            logger.error(f"Failed to initialize YTMusic: {e}")
            return None

    try:
        search_results = YT.search(artist_name, filter="artists", limit=1)
        if not search_results or not isinstance(search_results, list): return None
        artist_id = search_results[0].get('browseId')
        if not artist_id: return None
        artist_info = YT.get_artist(artist_id)
        thumbnails = artist_info.get('thumbnails')
        if thumbnails: return thumbnails[-1].get('url')
    except Exception as e:
        logger.error(f"YTMusic get_artist_image error for '{artist_name}': {e}")
    return None

async def download_audio(url: str, output_dir: Optional[str] = None, *, max_retries_per_method: int = 1, quality: int = 128) -> Optional[str]:
    url = _normalize_url(url)
    base_dir = output_dir if output_dir else os.path.join(os.getcwd(), "downloads")
    os.makedirs(base_dir, exist_ok=True)
    unique_id = uuid.uuid4().hex
    unique_dir = os.path.join(base_dir, unique_id)
    os.makedirs(unique_dir, exist_ok=True)

    before = set(Path(unique_dir).glob("*.mp3"))
    loop = asyncio.get_event_loop()

    for method in list(METHOD_ORDER):
        for attempt in range(1, max_retries_per_method + 1):
            try:
                opts = _build_opts(method, unique_dir, quality)
                def run_ydl():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                await loop.run_in_executor(None, run_ydl)
            except Exception as exc:
                logger.warning("Method %d failed: %s", method, exc)
                continue

            after = set(Path(unique_dir).glob("*.mp3"))
            new_files = after - before
            if new_files:
                mp3_path = max(new_files, key=lambda p: p.stat().st_mtime)
                return str(mp3_path)

    shutil.rmtree(unique_dir, ignore_errors=True)
    return None

def _normalize_url(url: str) -> str:
    import re
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if m:
        vid = m.group(1).split("?")[0]
        return f"https://www.youtube.com/watch?v={vid}"
    return url

def _build_opts(method: int, output_dir: str, preferred_quality: int) -> dict:
    opts = dict(COMMON_OPTS)
    opts["outtmpl"] = f"{output_dir}/%(title)s.%(ext)s"
    opts["format"] = "bestaudio/best"
    cookies_path = _get_cookies_path()
    if cookies_path: opts["cookiefile"] = cookies_path

    AUDIO_POSTPROCESSOR['preferredquality'] = str(preferred_quality)
    opts["postprocessors"] = [AUDIO_POSTPROCESSOR]
    if PROXY: opts["proxy"] = PROXY
    opts["http_headers"] = _get_random_headers()

    if method == 1:
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        opts["http_headers"]["User-Agent"] = "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
    elif method in [2, 6, 8]:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
    elif method == 3:
        opts["extractor_args"] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
    elif method in [4, 7]:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}
    elif method == 5:
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}

    return opts
