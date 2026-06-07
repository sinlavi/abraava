import aiosqlite
import asyncio
from lyricsgenius import Genius
from core.config import GENIUS_ACCESS_TOKEN, CACHE_DIR
import os
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("ABRAAVA:LYRICS_SERVICE")

class LyricsService:
    def __init__(self):
        self.genius = Genius(
            GENIUS_ACCESS_TOKEN,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            remove_section_headers=True,
            retries=2
        )
        self.genius.verbose = False
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

        # 2. Fetch from Genius
        lyrics = await self._fetch_from_genius(title, artist)

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

    async def _fetch_from_genius(self, title, artist):
        loop = asyncio.get_event_loop()
        try:
            # Clean up title/artist if needed
            search_query = f"{title} {artist}"
            song = await loop.run_in_executor(self._executor, self.genius.search_song, title, artist)

            if song:
                return song.lyrics
            return None
        except Exception as e:
            logger.error(f"Error fetching lyrics from Genius: {e}")
            return None

lyrics_service = LyricsService()
