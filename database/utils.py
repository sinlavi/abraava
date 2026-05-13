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


async def store_user(id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users (id,last_updated)
            VALUES (?,?)
        """, (
            str(id),
            int(time.time())
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


async def get_users_db(id: int):
    """Fetch artist from local DB and return in iTunes lookup format."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users WHERE id = ?", (id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return True
    return False


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


async def get_all_users():
    """Get all unique user IDs from database"""
    users = set()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT DISTINCT id FROM users") as cursor:
                async for row in cursor:
                    users.add(row[0])
    except:
        pass
    return list(users)


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

    if entity in ("artist"):
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

    if entity in ("album"):
        async with aiosqlite.connect(DB_PATH) as db:
            # فقط آلبوم‌هایی که بیش از ۱ ترک دارند، با استخراج artistName از فیلد JSON
            async with db.execute(
                    """
                    SELECT a.collectionId, a.collectionName, a.artworkUrl100, 
                           COUNT(t.trackId) as track_count,
                           json_extract(a.data, '$.artistName') as artistName
                    FROM album a
                    LEFT JOIN track t ON a.collectionId = t.collectionId
                    WHERE a.collectionName LIKE ? 
                    GROUP BY a.collectionId, a.collectionName, a.artworkUrl100, a.data
                    HAVING COUNT(t.trackId) > 1
                    LIMIT ?
                    """,
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "collection",
                        "collectionId": row[0],
                        "collectionName": row[1],
                        "artworkUrl100": row[2],
                        "trackCount": row[3],
                        "artistName": row[4]  # artistName از فیلد JSON
                    })

    if entity in ("track"):
        async with aiosqlite.connect(DB_PATH) as db:
            # استخراج artistName از فیلد JSON برای ترک‌ها
            async with db.execute(
                    """
                    SELECT trackId, collectionId, trackName, artworkUrl100,
                           json_extract(data, '$.artistName') as artistName,
                           json_extract(data, '$.artistId') as artistId
                    FROM track 
                    WHERE trackName LIKE ? 
                    LIMIT ?
                    """,
                    (pattern, 50)
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "wrapperType": "track",
                        "trackId": row[0],
                        "collectionId": row[1],
                        "trackName": row[2],
                        "artworkUrl100": row[3],
                        "artistName": row[4],  # artistName از فیلد JSON
                        "artistId": row[5]  # artistId از فیلد JSON
                    })

    # Trim to overall limit 50 if entity is "all"
    if entity == "all":
        results = results[:50]
    return {"resultCount": len(results), "results": results}
