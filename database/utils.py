import json
import time
from typing import Optional, Dict, Any

import aiosqlite

from database.config import DB_PATH


async def store_artist(item: dict):
    """Insert or replace an artist from iTunes API item into the artist table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO artist (artistId, artistName, primaryGenreName, artistLinkUrl, artworkUrl100, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item.get("artistId"),
            item.get("artistName", ""),
            item.get("primaryGenreName", ""),
            item.get("artistLinkUrl", ""),
            item.get("artworkUrl100", ""),
            json.dumps(item)
        ))
        await db.commit()


async def store_album(item: dict):
    """Insert or replace an album from iTunes API item into the album table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO album (collectionId, artistId, collectionName, releaseDate, 
                                          primaryGenreName, artworkUrl100, collectionViewUrl, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("collectionId"),
            item.get("artistId"),
            item.get("collectionName", ""),
            item.get("releaseDate", ""),
            item.get("primaryGenreName", ""),
            item.get("artworkUrl100", ""),
            item.get("collectionViewUrl", ""),
            json.dumps(item)
        ))
        await db.commit()


async def store_track(item: dict):
    """Insert or replace a track from iTunes API item into the track table."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO track (trackId, artistId, collectionId, trackName, trackTimeMillis,
                                          primaryGenreName, releaseDate, trackViewUrl, previewUrl,balePostId, artworkUrl100, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?)
        """, (
            item.get("trackId"),
            item.get("artistId"),
            item.get("collectionId"),
            item.get("trackName", ""),
            item.get("trackTimeMillis", 0),
            item.get("primaryGenreName", ""),
            item.get("releaseDate", ""),
            item.get("trackViewUrl", ""),
            item.get("previewUrl", ""),
            item.get("balePostId", 0),
            item.get("artworkUrl100", ""),
            json.dumps(item)
        ))
        await db.commit()


async def get_artist_db(artist_id: int) -> Optional[Dict[str, Any]]:
    """Fetch artist from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM artist WHERE artistId = ?", (artist_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                artist_data = json.loads(row[0])
                return {"resultCount": 1, "results": [artist_data]}
    return None


async def get_album_db(collection_id: int) -> Optional[Dict[str, Any]]:
    """Fetch album from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM album WHERE collectionId = ?", (collection_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                album_data = json.loads(row[0])
                return {"resultCount": 1, "results": [album_data]}
    return None


async def get_track_db(track_id: int) -> Optional[Dict[str, Any]]:
    """Fetch track from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM track WHERE trackId = ?", (track_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                track_data = json.loads(row[0])
                return {"resultCount": 1, "results": [track_data]}
    return None


async def get_cached(id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM cache WHERE id = ?", (id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
    return None


async def set_cached(id: str, type: str, data: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO cache (id, type, data, last_updated)
            VALUES (?, ?, ?, ?)
        """, (id, type, json.dumps(data), int(time.time())))
        await db.commit()


async def delete_cached(id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cache WHERE id = ?", (id,))
        await db.commit()


async def is_cached(id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM cache WHERE id = ?", (id,)) as cursor:
            return await cursor.fetchone() is not None


async def get_audio_cache(track_id: int) -> Optional[int]:
    """Get cached balePostId for a track if it exists and is not 0."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balePostId FROM track WHERE trackId = ? AND balePostId != 0", 
            (track_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_audio_cache(track_id: int, bale_post_id: int):
    """Update the balePostId for an existing track."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE track SET balePostId = ? WHERE trackId = ?",
            (bale_post_id, track_id)
        )
        await db.commit()

async def local_search(term: str, entity: str = "all") -> Optional[Dict[str, Any]]:
    """Search the local relational database for the given term."""
    results = []
    pattern = f"%{term}%"

    if entity in ("artist", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT artistId, artistName, primaryGenreName, artworkUrl100, artistLinkUrl FROM artist WHERE artistName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "artist",
                        "artistId": row[0],
                        "artistName": row[1],
                        "primaryGenreName": row[2],
                        "artworkUrl100": row[3],
                        "artistLinkUrl": row[4]
                    })

    if entity in ("album", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT collectionId, artistId, collectionName, artworkUrl100 FROM album WHERE collectionName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "collection",
                        "collectionId": row[0],
                        "artistId": row[1],
                        "collectionName": row[2],
                        "artworkUrl100": row[3]
                    })

    if entity in ("track", "all"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT trackId, artistId, collectionId, trackName, artworkUrl100 FROM track WHERE trackName LIKE ? LIMIT ?",
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "track",
                        "trackId": row[0],
                        "artistId": row[1],
                        "collectionId": row[2],
                        "trackName": row[3],
                        "artworkUrl100": row[4]
                    })

    # Trim to overall limit 50 if entity is "all"
    if entity == "all":
        results = results[:50]
    return {"resultCount": len(results), "results": results}
