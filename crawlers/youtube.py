import asyncio
import os
import shutil
import uuid
import random
import re
import socket
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import yt_dlp
from ytmusicapi import YTMusic
from rapidfuzz import fuzz

from core.logger import logger
from core.config import OFFLINE_MODE, PROXY

YT: Optional[YTMusic] = None

# Global method orders to track what works best
# 1-8: Proxy methods, 11-18: Non-proxy methods
SEARCH_METHOD_ORDER = [1, 2, 3, 11, 12, 13]
METHOD_ORDER = [1, 11, 2, 12, 3, 13, 4, 14, 5, 15, 6, 16, 7, 17, 8, 18]

# Common yt-dlp options
COMMON_OPTS = {
    "format": "bestaudio/bestaudio*",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

AUDIO_POSTPROCESSOR = {
    "key": "FFmpegExtractAudio",
    "preferredcodec": "mp3",
    "preferredquality": "128",
}


def _get_cookies_path() -> Optional[str]:
    """
    Get the path to cookies.txt in the root project folder.
    """
    script_dir = Path(__file__).parent.parent
    cookies_path = script_dir / "cookies.txt"

    if cookies_path.exists() and cookies_path.is_file():
        logger.info(f"Found cookies file at: {cookies_path}")
        return str(cookies_path)
    else:
        logger.debug(f"No cookies.txt found at: {cookies_path}")
        return None


def _check_deno() -> bool:
    """Check if deno is installed and available in PATH."""
    return shutil.which("deno") is not None


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
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/",
    }


def _calculate_relevance_score(result: dict, t_name: str, a_name: str, collection_name: str, ye: str) -> float:
    res_title = result.get('title', '')
    res_uploader = result.get('uploader', '')
    res_description = result.get('description', '')

    score = 0.0
    # Title match (Highest weight)
    score += fuzz.WRatio(t_name, res_title) * 0.5

    # Artist match
    artist_score = max(fuzz.WRatio(a_name, res_uploader), fuzz.WRatio(a_name, res_description))
    score += artist_score * 0.3

    # Album/Year context
    context_score = 0.0
    if collection_name:
        context_score = max(context_score, fuzz.partial_ratio(collection_name, res_title) * 0.1)
        context_score = max(context_score, fuzz.partial_ratio(collection_name, res_description) * 0.1)

    if ye:
        if ye in res_title or ye in (result.get('upload_date', '') or ''):
            context_score = max(context_score, 10.0)

    score += context_score
    return score / 100.0


async def search_youtube_track(t_name: str, a_name: str, collection_name: str, ye: str) -> Optional[str]:
    """
    Search for a track on YouTube and return the best matching video ID.
    Uses multiple methods including YTMusic API and yt-dlp search.
    """
    global SEARCH_METHOD_ORDER

    logger.info(f"Searching for: {t_name} by {a_name}")

    best_result = None
    best_score = -1.0

    for method in list(SEARCH_METHOD_ORDER):
        try:
            if method == 1:  # YTMusic API (Always tries to use proxy internally)
                loop = asyncio.get_event_loop()
                result_id = await loop.run_in_executor(None, _sync_search_youtube, t_name, a_name, collection_name, ye)
                if result_id:
                    logger.info(f"YTMusic found match: {result_id}")
                    return result_id

            elif method in [2, 3, 12, 13]:  # yt-dlp search
                limit = 5 if method in [2, 12] else 3
                query_suffix = " official audio" if method in [2, 12] else " topic"
                search_query = f"ytsearch{limit}:{t_name} {a_name} {collection_name}{query_suffix}"

                opts = _build_search_ydl_opts(method, 128)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
                    if info and 'entries' in info and info['entries']:
                        for entry in info['entries']:
                            if not entry: continue
                            score = _calculate_relevance_score(entry, t_name, a_name, collection_name, ye)
                            if score > best_score:
                                best_score = score
                                best_result = entry.get('id')

            if best_result and best_score > 0.8:
                logger.info(f"Found high-confidence match with method {method} (score: {best_score:.2f})")

                # Update method order
                if method in SEARCH_METHOD_ORDER:
                    SEARCH_METHOD_ORDER.remove(method)
                    SEARCH_METHOD_ORDER.insert(0, method)
                break

        except Exception as e:
            logger.debug(f"Search method {method} failed: {e}")

    return best_result


def _build_search_ydl_opts(method: int, preferred_quality: int) -> dict:
    """
    Build yt‑dlp options specifically for searching.
    1-10: Proxy enabled, 11-20: Proxy disabled.
    """
    opts = dict(COMMON_OPTS)
    opts["quiet"] = True
    opts["no_warnings"] = True
    opts["extract_flat"] = False
    opts["skip_download"] = True

    cookies_path = _get_cookies_path()
    if cookies_path:
        opts["cookiefile"] = cookies_path

    opts["http_headers"] = _get_random_headers()

    # Proxy selection logic
    if 1 <= method <= 10:
        proxy = _check_proxy() or PROXY
        if proxy:
            opts["proxy"] = proxy
            logger.debug(f"Search Method {method}: Proxy enabled -> {proxy}")
    else:
        logger.debug(f"Search Method {method}: Proxy disabled")

    # Client selection
    norm_method = method % 10
    if norm_method == 1:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
    elif norm_method == 2:
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}

    return opts


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
        cookies = _get_cookies_path()
        try:
            # Note: YTMusic doesn't have a direct 'proxy' param in init for socks5 easily
            # but it respects system/env proxies if set.
            YT = YTMusic(auth=cookies) if cookies else YTMusic()
        except Exception as e:
            logger.error(f"Failed to initialize YTMusic: {e}")
            YT = YTMusic()

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

        return best_match_id

    except Exception as e:
        logger.error(f"YTMusic search error: {e}")

    return None


def get_artist_image(artist_name):
    """Get artist image from YTMusic with improved error handling"""
    global YT
    if YT is None:
        cookies = _get_cookies_path()
        try:
            YT = YTMusic(auth=cookies) if cookies else YTMusic()
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
                # Move failed method to end of its category (proxy or non-proxy)
                if method in METHOD_ORDER:
                    METHOD_ORDER.remove(method)
                    METHOD_ORDER.append(method)

                await asyncio.sleep(random.uniform(0.5, 1.5))
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
                await asyncio.sleep(random.uniform(0.5, 1.0))

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
    Build yt‑dlp options dict for the given method number.
    1-10: Proxy enabled, 11-20: Proxy disabled.
    """
    opts = dict(COMMON_OPTS)
    opts["outtmpl"] = f"{output_dir}/%(title)s.%(ext)s"
    opts["format"] = "bestaudio/bestaudio*"

    cookies_path = _get_cookies_path()
    if cookies_path:
        opts["cookiefile"] = cookies_path
        logger.debug(f"Using cookies from: {cookies_path}")

    AUDIO_POSTPROCESSOR['preferredquality'] = str(preferred_quality)
    opts["postprocessors"] = [AUDIO_POSTPROCESSOR]

    has_deno = _check_deno()

    # Proxy selection logic
    if 1 <= method <= 10:
        proxy = _check_proxy() or PROXY
        if proxy:
            opts["proxy"] = proxy
            logger.debug(f"Download Method {method}: Proxy enabled -> {proxy}")
    else:
        logger.debug(f"Download Method {method}: Proxy disabled")

    opts["http_headers"] = _get_random_headers()

    norm_method = method % 10

    if norm_method == 8:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif norm_method == 2:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:npm"]

    elif norm_method == 3:
        opts["extractor_args"] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif norm_method == 4:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif norm_method == 5:
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}

    elif norm_method == 6:
        opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        if has_deno:
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]

    elif norm_method == 7:
        opts["extractor_args"] = {"youtube": {"player_client": ["mweb"]}}

    elif norm_method == 1:
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        opts["http_headers"]["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
        )

    return opts
