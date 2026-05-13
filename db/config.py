import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiosqlite

from config import logger
from db.models import TrackSchema, CollectionSchema, SCHEMAS, ArtistSchema, CacheSchema, ENTITY_ALIASES

DB_PATH = Path("./abraava.db")


# ============================================================================
# Global Instance & Convenience Functions
# ============================================================================
class Database:
    """Thin wrapper around aiosqlite with schema-aware operations."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    async def init(self):
        """Create all tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    last_updated INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    term TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    cacheId TEXT PRIMARY KEY,
                    content TEXT NOT NULL
                )
            """)

            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS artist (
                    {ArtistSchema.COLUMNS_DEF}
                )
            """)
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS collection (
                    {CollectionSchema.COLUMNS_DEF}
                )
            """)
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS track (
                    {TrackSchema.COLUMNS_DEF}
                )
            """)
            await db.commit()

    async def insert(self, schema_name: str, item: dict):
        """Insert or replace an entity using its schema."""
        schema = SCHEMAS[schema_name]
        values = schema.from_api_item(item)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(schema.INSERT_SQL, values)
            await db.commit()

    async def get_by_id(self, schema_name: str, entity_id: int) -> Optional[Dict[str, Any]]:
        """Fetch single entity by ID, returns iTunes format or None."""
        schema = SCHEMAS[schema_name]
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(schema.GET_BY_ID_SQL, (entity_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "resultCount": 1,
                        "results": [schema.to_api_response(row)]
                    }
        return None

    async def _resolve_entity(self, entity: str) -> str:
        """Resolve entity aliases to canonical names."""
        entity = entity.lower()
        return ENTITY_ALIASES.get(entity, entity)

    # ========== Search (delegated to Schema) ==========

    async def search(self, term: str, entity: str = "all") -> Dict[str, Any]:
        """Search local database by term across specified entity types."""
        entity = await self._resolve_entity(entity)
        pattern = f"%{term}%"
        results = []

        async with aiosqlite.connect(self.db_path) as db:
            if entity == "all":
                for schema in [ArtistSchema, CollectionSchema, TrackSchema]:
                    rows = await self._search_entity(db, schema, pattern, 200)
                    results.extend(rows)
                results = results[:200]
            elif entity in SCHEMAS:
                schema = SCHEMAS[entity]
                results = await self._search_entity(db, schema, pattern, 200)

        return {"resultCount": len(results), "results": results}

    async def _search_entity(self, db, schema, pattern: str, limit: int) -> List[dict]:
        """Execute search for a single entity type."""
        results = []
        async with db.execute(schema.SEARCH_SQL, (pattern, limit)) as cursor:
            async for row in cursor:
                results.append(schema.to_search_result(row))
        return results

    async def insert_search_cache(self, search_id: str, type_: str, term: str, data: dict):
        """Cache search results for pagination."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO search_cache (id, type, term, data, timestamp) VALUES (?, ?, ?, ?, ?)",
                (search_id, type_, term, json.dumps(data), int(time.time()))
            )
            await db.commit()

    async def get_search_cache(self, search_id: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT type, term, data FROM search_cache WHERE id = ?", (search_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"type": row[0], "term": row[1], "data": json.loads(row[2])}
        return None

    async def force_recrawl_artist(self, artist_id: int):
        """Clear artist relations to force re-crawl."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM collection WHERE artistId = ?", (artist_id,))
            await db.execute("DELETE FROM track WHERE artistId = ?", (artist_id,))
            await db.commit()

    async def force_recrawl_collection(self, collection_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM track WHERE collectionId = ?", (collection_id,))
            await db.commit()

    async def force_recrawl_track(self, track_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM track WHERE trackId = ?", (track_id,))
            await db.commit()

    # ========== Relations (delegated to Schema) ==========

    async def get_artist_tracks(self, artist_id: int) -> Dict[str, Any]:
        """Return all tracks by an artist, full field mapping."""
        tracks = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(ArtistSchema.TRACKS_SQL, (artist_id,)) as cursor:
                async for row in cursor:
                    tracks.append(self._map_artist_track_row(row))
        return {"resultCount": len(tracks), "results": tracks}

    async def get_artist_collections(self, artist_id: int) -> Dict[str, Any]:
        """Return all collections by an artist, full field mapping."""
        collections = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(ArtistSchema.COLLECTIONS_SQL, (artist_id,)) as cursor:
                async for row in cursor:
                    collections.append(ArtistSchema.collection_row_to_response(row))
        return {"resultCount": len(collections), "results": collections}

    async def get_collection_tracks(self, collection_id: int) -> Dict[str, Any]:
        """Return all tracks for a collection, full field mapping."""
        tracks = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT * FROM track WHERE collectionId = ' + str(collection_id)) as cursor:
                async for row in cursor:
                    tracks.append(self._map_collection_track_row(row))
        return {"resultCount": len(tracks), "results": tracks}

    # ========== Audio Cache ==========

    async def get_cache(self, cache_id: int) -> Optional[int]:
        """Get cached balePostId for a track."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(CacheSchema.CACHE_GET_SQL, (cache_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set_cache(self, cache_id: int, value: str):
        """Update the balePostId for a track."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(CacheSchema.CACHE_SET_SQL, (value, cache_id))
            await db.commit()

    # ========== User Management ==========

    async def insert_user(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO users (id, last_updated) VALUES (?, ?)",
                (str(user_id), int(time.time()))
            )
            await db.commit()

    async def get_user_exists(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM users WHERE id = ?", (str(user_id),)) as cursor:
                return await cursor.fetchone() is not None

    async def get_all_users(self) -> List[str]:
        users = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT DISTINCT id FROM users") as cursor:
                async for row in cursor:
                    users.append(row[0])
        return users

    # ========== Row Mappers for Relations ==========

    def _map_artist_track_row(self, row: tuple) -> dict:
        """Map Artist.TRACKS_SQL result to full track dict."""
        return {
            "wrapperType": "track",
            "trackId": row[0],
            "trackName": row[1],
            "collectionId": row[2],
            "collectionName": row[3],
            "artworkUrl100": row[4],
            "artistName": row[5],
            "primaryGenreName": row[6],
            "releaseDate": row[7],
            "previewUrl": row[8],
            "trackTimeMillis": row[9],
            "trackNumber": row[10],
            "trackCount": row[11],
            "trackViewUrl": row[12],
            "country": row[13],
        }

    def _map_collection_track_row(self, row: tuple) -> dict:
        """Map Collection.TRACKS_SQL result to full track dict."""
        return {
            "wrapperType": "track",
            "trackId": row[0],
            "trackNumber": row[1],
            "trackCount": row[2],
            "trackName": row[3],
            "trackCensoredName": row[4],
            "trackTimeMillis": row[5],
            "discCount": row[6],
            "discNumber": row[7],
            "collectionId": row[8],
            "collectionName": row[9],
            "collectionCensoredName": row[10],
            "artistId": row[11],
            "artistName": row[12],
            "primaryGenreName": row[13],
            "releaseDate": row[14],
            "previewUrl": row[15],
            "trackViewUrl": row[16],
            "artworkUrl": row[17],
            "country": row[18],
        }


db = Database()
