import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("ABRAAVA:DB")

DB_PATH = Path("./abraava.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Preserve old cache table if needed (for search result caching)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                last_updated INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                last_updated INTEGER NOT NULL
            )
        """)
        # New relational tables
        await db.execute("""
            CREATE TABLE IF NOT EXISTS artist (
                artistId INTEGER PRIMARY KEY,
                artistName TEXT,
                primaryGenreName TEXT,
                artistLinkUrl TEXT,
                artworkUrl100 TEXT,
                data TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS album (
                collectionId INTEGER PRIMARY KEY,
                artistId INTEGER,
                collectionName TEXT,
                releaseDate TEXT,
                primaryGenreName TEXT,
                artworkUrl100 TEXT,
                collectionViewUrl TEXT,
                data TEXT,
                FOREIGN KEY (artistId) REFERENCES artist(artistId)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS track (
                trackId INTEGER PRIMARY KEY,
                artistId INTEGER,
                collectionId INTEGER,
                trackName TEXT,
                trackTimeMillis INTEGER,
                primaryGenreName TEXT,
                releaseDate TEXT,
                trackViewUrl TEXT,
                balePostId INTEGER NOT NULL,
                previewUrl TEXT,
                artworkUrl100 TEXT,
                data TEXT,
                FOREIGN KEY (artistId) REFERENCES artist(artistId),
                FOREIGN KEY (collectionId) REFERENCES album(collectionId)
            )
        """)
        await db.commit()
    logger.info("Database initialized successfully (relational tables ready).")
