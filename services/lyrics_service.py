import aiosqlite
import asyncio
from ytmusicapi import YTMusic
from core.config import CACHE_DIR
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from crawlers.youtube import search_youtube_track
from pathlib import Path
import http.cookiejar

logger = logging.getLogger("ABRAAVA:LYRICS_SERVICE")

def _load_cookies_as_header(cookie_file):
    """Load Netscape cookies.txt and return a Cookie header string."""
    try:
        if not os.path.exists(cookie_file):
            return None
        cj = http.cookiejar.MozillaCookieJar(cookie_file)
        cj.load(ignore_discard=True, ignore_expires=True)
        cookies = []
        for cookie in cj:
            cookies.append(f"{cookie.name}={cookie.value}")
        return "; ".join(cookies)
    except Exception as e:
        logger.error(f"Error loading cookies from {cookie_file}: {e}")
        return None

class LyricsService:
    def __init__(self):
        cookies_path = "cookies.txt"
        cookie_header = _load_cookies_as_header(cookies_path)

        self.ytm = YTMusic()
        if cookie_header:
            logger.info(f"Adding Cookie header from: {cookies_path}")
            # Injecting the cookie header into the session headers
            self.ytm.headers["Cookie"] = cookie_header

        self.db_path = os.path.join(CACHE_DIR, "lyrics.db")
        self._executor = ThreadPoolExecutor(max_workers=5)

        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS lyrics (
                    track_id TEXT PRIMARY KEY,
                    lyrics TEXT,
                    title TEXT,
                    artist TEXT
                )
            """)
            await db.commit()

    async def get_lyrics(self, track_id, title, artist):
        # 1. Check Cache
        cached_lyrics = await self._get_cached_lyrics(track_id)
        if cached_lyrics:
            return cached_lyrics

        # 2. Fetch from YTMusic
        lyrics = await self._fetch_from_ytmusic(track_id, title, artist)

        if lyrics:
            # 3. Cache it
            await self._cache_lyrics(track_id, lyrics, title, artist)

        return lyrics

    async def _get_cached_lyrics(self, track_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT lyrics FROM lyrics WHERE track_id = ?", (str(track_id),)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def _cache_lyrics(self, track_id, lyrics, title, artist):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO lyrics (track_id, lyrics, title, artist) VALUES (?, ?, ?, ?)",
                (str(track_id), lyrics, title, artist)
            )
            await db.commit()

    async def _fetch_from_ytmusic(self, track_id, title, artist):
        try:
            video_id = None
            if track_id.startswith("yt_"):
                video_id = track_id[3:]
            else:
                # Search for the track on YouTube
                video_id = await search_youtube_track(title, artist, "", "")

            if not video_id:
                logger.warning(f"Could not find YouTube video for {title} - {artist}")
                return None

            loop = asyncio.get_event_loop()

            # Get watch playlist to find lyrics browse ID
            watch_playlist = await loop.run_in_executor(
                self._executor,
                lambda: self.ytm.get_watch_playlist(video_id)
            )

            lyrics_browse_id = watch_playlist.get('lyrics')
            if not lyrics_browse_id:
                logger.info(f"No lyrics found for {title} - {artist} (Video ID: {video_id})")
                return None

            # Fetch the actual lyrics
            lyrics_data = await loop.run_in_executor(
                self._executor,
                lambda: self.ytm.get_lyrics(lyrics_browse_id)
            )

            return lyrics_data.get('lyrics')

        except Exception as e:
            logger.error(f"Error fetching lyrics from YTMusic: {e}")
            return None

lyrics_service = LyricsService()
