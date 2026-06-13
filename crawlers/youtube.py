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
    PROXY = "socks5h://127.0.0.1:1080"

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
METHOD_ORDER = [8, 2, 3, 4, 5, 6, 7, 1]

# ── Search Method Order (same as download methods) ───────────────────────
SEARCH_METHOD_ORDER = [8, 2, 3, 4, 5, 6, 7, 1]

# ============================================================================
# YouTube Music Helper
# ============================================================================
YT = None


def _get_cookies_path() -> Optional[str]:
    """
    Get the path to cookies.txt in the root project folder.
    Returns None if the file doesn't exist.
    """
    script_dir = Path(__file__).parent
    cookies_path = script_dir / "cookies.txt"
    
    if cookies_path.exists() and cookies_path.is_file():
        logger.info(f"Found cookies file at: {cookies_path}")
        return str(cookies_path)
    else:
        logger.debug(f"No cookies.txt found at: {cookies_path}")
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


def _build_search_ydl_opts(method: int, preferred_quality: int) -> dict:
    """
    Build yt‑dlp options specifically for searching (extract info only).
    """
    opts = dict(COMMON_OPTS)
    opts["quiet"] = True
    opts["no_warnings"] = True
    opts["extract_flat"] = False  # Get full info
    opts["skip_download"] = True  # Don't download, just extract info
    
    cookies_path = _get_cookies_path()
    if cookies_path:
        opts["cookiefile"] = cookies_path
    
    opts["http_headers"] = _get_random_headers()
    
    has_deno = _check_deno()
    opts["proxy"] = PROXY
    
    # Same method-specific configurations as download
    if method == 8:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]
    
    elif method == 2:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:npm"]
    
    elif method == 3:
        opts["extractor_args"] = {
            "youtube": {"player_client": ["web", "mweb", "android_vr"]}
        }
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]
    
    elif method == 4:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}
    
    elif method == 5:
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}
    
    elif method == 6:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]
    
    elif method == 7:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}
    
    elif method == 1:
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        opts["http_headers"]["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
        )
    
    return opts


def _search_with_ytdlp(search_query: str, method: int) -> Optional[dict]:
    """
    Search YouTube using yt-dlp with specific method.
    Returns the best matching video info or None.
    """
    try:
        opts = _build_search_ydl_opts(method, 128)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Search query format for yt-dlp
            search_url = f"ytsearch10:{search_query}"
            info = ydl.extract_info(search_url, download=False)
            
            if info and 'entries' in info and info['entries']:
                # Return the first result
                return info['entries'][0]
            
    except Exception as e:
        logger.debug(f"Search method {method} failed: {e}")
    
    return None


def _calculate_relevance_score(video_info: dict, t_name: str, a_name: str, collection_name: str, ye: str) -> float:
    """
    Calculate relevance score for a search result.
    """
    title = video_info.get('title', '')
    channel = video_info.get('channel', '')
    uploader = video_info.get('uploader', '')
    upload_date = video_info.get('upload_date', '')
    
    score = 0.0
    
    # Title matching (45% weight)
    score += _get_similarity(t_name, title) * 0.45
    
    # Artist/channel matching (35% weight)
    artist_text = f"{channel} {uploader}"
    score += _get_similarity(a_name, artist_text) * 0.35
    
    # Album/collection matching (15% weight)
    if collection_name:
        # Check if collection name appears in title or description
        description = video_info.get('description', '')
        if collection_name.lower() in title.lower() or collection_name.lower() in description.lower():
            score += 0.15
    
    # Year matching (5% weight)
    if ye and upload_date:
        video_year = upload_date[:4] if len(upload_date) >= 4 else ''
        if str(ye) == video_year:
            score += 0.05
    
    return score


async def search_youtube_track(t_name: str, a_name: str, collection_name: str, ye: str) -> Optional[str]:
    """
    Search for a YouTube track using multiple methods (same as download).
    Returns video ID or None.
    """
    global SEARCH_METHOD_ORDER
    
    if OFFLINE_MODE:
        logger.info("Offline mode: skipping YouTube search")
        return None
    
    # First try YTMusic as it's faster for searches
    try:
        loop = asyncio.get_event_loop()
        ytmusic_id = await loop.run_in_executor(None, _sync_search_youtube, t_name, a_name, collection_name, ye)
        if ytmusic_id:
            logger.info(f"✅ YTMusic search successful: {ytmusic_id}")
            return ytmusic_id
    except Exception as e:
        logger.debug(f"YTMusic search failed: {e}")
    
    # Build search query
    search_query = f"{t_name} {a_name}".strip()
    if collection_name:
        search_query += f" {collection_name}"
    
    best_result = None
    best_score = -1.0
    successful_methods = []
    
    # Try each method in order
    for method in list(SEARCH_METHOD_ORDER):
        logger.debug(f"Searching with method {method}")
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _search_with_ytdlp, search_query, method)
            
            if result and result.get('id'):
                # Calculate relevance score
                score = _calculate_relevance_score(result, t_name, a_name, collection_name, ye)
                
                logger.debug(f"Method {method} found: {result.get('title', 'N/A')} (score: {score:.2f})")
                
                title_sim = _get_similarity(t_name, result.get('title', ''))
                if score > best_score:
                    best_score = score
                    best_result = result.get('id')
                    best_title_sim = title_sim
                    successful_methods.append(method)
                    
                    # Update method order (bring successful method to front)
                    if method in SEARCH_METHOD_ORDER:
                        SEARCH_METHOD_ORDER.remove(method)
                        SEARCH_METHOD_ORDER.insert(0, method)
                    
                    # If score is very high (90%+), stop searching
                    if score >= 0.9:
                        logger.info(f"Found excellent match with method {method} (score: {score:.2f})")
                        break
            
            # Random delay between methods to avoid rate limiting
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            logger.debug(f"Search method {method} error: {e}")
            # Move failed method to the end
            if method in SEARCH_METHOD_ORDER:
                SEARCH_METHOD_ORDER.remove(method)
                SEARCH_METHOD_ORDER.append(method)
    
    if best_result:
        # Title similarity check for the best result
        if best_score < 0.45 or best_title_sim < 0.4:
            logger.warning(f"Best match found but score too low (score: {best_score:.2f}, title_sim: {best_title_sim:.2f}): {t_name} - {a_name}")
            return None

        logger.info(f"Search successful with methods: {successful_methods}, best score: {best_score:.2f}, title_sim: {best_title_sim:.2f}")
        return best_result
    else:
        logger.warning(f"No search results found for: {t_name} - {a_name}")
        return None


# Helper function for similarity (keeping existing implementation)
def _get_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.WRatio(str(a), str(b)) / 100.0


def _sync_search_youtube(t_name: str, a_name: str, collection_name: str, ye: str) -> Optional[str]:
    """
    Original YTMusic search as fallback.
    """
    global YT
    if YT is None:
        YT = YTMusic(proxies={"https": PROXY, "http": PROXY})

    search_query = f"{t_name} {a_name} {collection_name}".strip()

    try:
        results = YT.search(search_query, filter="songs", limit=10)

        if not results or not isinstance(results, list):
            return None

        best_match_id = None
        highest_score = -1.0

        for res in results:
            res_title = res.get("title", "")
            artists = res.get("artists", [])
            res_artist = ", ".join([a.get("name", "") for a in artists]) if artists else ""
            album_data = res.get("album") or {}
            res_album = album_data.get("name", "")
            res_year = res.get("year", "")

            score = 0.0
            score += _get_similarity(t_name, res_title) * 0.45
            score += _get_similarity(a_name, res_artist) * 0.35
            score += _get_similarity(collection_name, res_album) * 0.15

            if ye and res_year:
                if str(ye) == str(res_year):
                    score += 0.05

            if score > highest_score:
                highest_score = score
                best_match_id = res.get("videoId")
                best_title = res_title

        if best_match_id:
            title_sim = _get_similarity(t_name, best_title)
            if highest_score < 0.45 or title_sim < 0.4:
                logger.warning(f"YTMusic best match score too low (score: {highest_score:.2f}, title_sim: {title_sim:.2f})")
                return None

        return best_match_id

    except Exception as e:
        logger.error(f"YTMusic search error: {e}")

    return None


def get_artist_image(artist_name):
    """Get artist image from YTMusic with improved error handling"""
    global YT
    if YT is None:
        try:
            YT = YTMusic(proxies={"https": PROXY, "http": PROXY})
        except Exception as e:
            logger.error(f"Failed to initialize YTMusic: {e}")
            return None

    try:
        search_results = YT.search(artist_name, filter="artists", limit=1)
        if not search_results or not isinstance(search_results, list):
            return None

        artist_id = search_results[0].get('browseId')
        if not artist_id:
            return None

        artist_info = YT.get_artist(artist_id)
        if not artist_info or not isinstance(artist_info, dict):
            return None

        thumbnails = artist_info.get('thumbnails')
        if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
            # thumbnails are usually sorted by size, but we'll try to find the one with highest resolution
            # or just take the first one which is standard for get_artist
            return thumbnails[-1].get('url')

    except Exception as e:
        logger.error(f"YTMusic get_artist_image error for '{artist_name}': {e}")

    return None


async def download_audio(
        url: str,
        output_dir: Optional[str] = None,
        *,
        max_retries_per_method: int = 1,
        quality: int = 128,
) -> Optional[str]:
    """
    Download YouTube audio as MP3.
    """
    global METHOD_ORDER
    preferred_quality = quality
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
    loop = asyncio.get_event_loop()

    for method in list(METHOD_ORDER):
        for attempt in range(1, max_retries_per_method + 1):
            logger.info("▶ Try Method %d (Attempt %d)", method, attempt)
            try:
                opts = _build_opts(method, unique_dir, preferred_quality)

                def run_ydl():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])

                await loop.run_in_executor(None, run_ydl)

            except Exception as exc:
                logger.warning("Method %d failed: %s", method, exc)
                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.append(method)

                await asyncio.sleep(random.uniform(1.5, 3.0))
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
                await asyncio.sleep(random.uniform(1.0, 2.0))

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


def _build_opts(method: int, output_dir: str, preferred_quality: int) -> dict:
    """
    Build yt‑dlp options dict for the given method number (1‑8).
    """
    opts = dict(COMMON_OPTS)
    opts["outtmpl"] = f"{output_dir}/%(title)s.%(ext)s"
    opts["format"] = "bestaudio/best"

    cookies_path = _get_cookies_path()
    if cookies_path:
        opts["cookiefile"] = cookies_path
        logger.debug(f"Using cookies from: {cookies_path}")
    else:
        logger.debug("No cookies.txt found, proceeding without cookies")

    AUDIO_POSTPROCESSOR['preferredquality'] = str(preferred_quality)
    opts["postprocessors"] = [AUDIO_POSTPROCESSOR]

    has_deno = _check_deno()
    opts["proxy"] = PROXY

    opts["http_headers"] = _get_random_headers()

    if method == 8:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 2:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:npm"]

    elif method == 3:
        opts["extractor_args"] = {
            "youtube": {"player_client": ["web", "mweb", "android_vr"]}
        }
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 4:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif method == 5:
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}

    elif method == 6:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif method == 7:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif method == 1:
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        opts["http_headers"]["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
        )

    return opts
