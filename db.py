import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiosqlite

DB_PATH = Path("./abraava.db")


# ============================================================================
# Schema Classes with Full Encapsulation
# ============================================================================

class ArtistSchema:
    """Artist table schema, CRUD, search, and relations."""

    TABLE = "artist"
    PK = "artistId"

    COLUMNS_DEF = """
        artistId INTEGER PRIMARY KEY,
        artistName TEXT,
        biography TEXT,
        primaryGenreName TEXT,
        artistLinkUrl TEXT,
        artworkUrl TEXT
    """

    INSERT_COLUMNS = [
        "artistId", "artistName", "biography",
        "primaryGenreName", "artistLinkUrl", "artworkUrl"
    ]

    SELECT_COLUMNS = "*"

    INSERT_SQL = f"""
        INSERT OR REPLACE INTO artist 
        ({', '.join(INSERT_COLUMNS)})
        VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))})
    """

    GET_BY_ID_SQL = f"SELECT {SELECT_COLUMNS} FROM artist WHERE artistId = ?"

    SEARCH_SQL = f"""
        SELECT artistId, artistName, primaryGenreName, artworkUrl, artistLinkUrl
        FROM artist 
        WHERE artistName LIKE ? 
        LIMIT ?
    """

    # Relations
    TRACKS_SQL = """
        SELECT trackId, trackName, collectionId, collectionName, artworkUrl,
               artistName, primaryGenreName, releaseDate, previewUrl, trackTimeMillis,
               trackNumber, trackCount, trackViewUrl, country
        FROM track 
        WHERE artistId = ? 
        ORDER BY releaseDate DESC
    """

    COLLECTIONS_SQL = """
        SELECT collectionId, collectionName, collectionViewUrl, artworkUrl,
               artistName, releaseDate, primaryGenreName, trackCount, copyright, country
        FROM collection 
        WHERE artistId = ? 
        ORDER BY releaseDate DESC
    """

    # ========== Conversion Methods ==========

    @staticmethod
    def from_api_item(item: dict) -> tuple:
        """Extract fields from iTunes API response into DB tuple."""
        return (
            item.get("artistId"),
            item.get("artistName", ""),
            item.get("biography", ""),
            item.get("primaryGenreName", ""),
            item.get("artistLinkUrl", ""),
            item.get("artworkUrl100", ""),
        )

    @staticmethod
    def to_api_response(row: tuple) -> dict:
        """Convert full DB row to iTunes-like dict."""
        return {
            "wrapperType": "artist",
            "artistId": row[0],
            "artistName": row[1],
            "biography": row[2],
            "primaryGenreName": row[3],
            "artistLinkUrl": row[4],
            "artworkUrl100": row[5],
        }

    @staticmethod
    def to_search_result(row: tuple) -> dict:
        """Convert search result row to iTunes-like dict (partial fields)."""
        return {
            "wrapperType": "artist",
            "artistId": row[0],
            "artistName": row[1],
            "primaryGenreName": row[2],
            "artworkUrl100": row[3],
            "artistLinkUrl": row[4],
        }


class CollectionSchema:
    """Collection (album) table schema, CRUD, search, and relations."""

    TABLE = "collection"
    PK = "collectionId"

    COLUMNS_DEF = """
        collectionId INTEGER PRIMARY KEY,
        collectionType TEXT,
        collectionName TEXT,
        collectionCensoredName TEXT,
        collectionViewUrl TEXT,
        trackCount INTEGER,
        artistId INTEGER,
        artistName TEXT,
        releaseDate TEXT,
        primaryGenreName TEXT,
        artworkUrl TEXT,
        copyright TEXT,
        country TEXT,
        FOREIGN KEY (artistId) REFERENCES artist(artistId)
    """

    INSERT_COLUMNS = [
        "collectionId", "collectionType", "collectionName",
        "collectionCensoredName", "collectionViewUrl", "trackCount",
        "artistId", "artistName", "releaseDate", "primaryGenreName",
        "artworkUrl", "copyright", "country"
    ]

    SELECT_COLUMNS = "*"

    INSERT_SQL = f"""
        INSERT OR REPLACE INTO collection 
        ({', '.join(INSERT_COLUMNS)})
        VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))})
    """

    GET_BY_ID_SQL = f"SELECT {SELECT_COLUMNS} FROM collection WHERE collectionId = ?"

    SEARCH_SQL = """
        SELECT c.collectionId, c.collectionName, c.artworkUrl, c.artistName,
               c.collectionViewUrl, c.releaseDate, c.primaryGenreName, 
               c.copyright, c.country,
               COUNT(t.trackId) as actualTrackCount
        FROM collection c
        LEFT JOIN track t ON c.collectionId = t.collectionId
        WHERE c.collectionName LIKE ?
        GROUP BY c.collectionId
        HAVING COUNT(t.trackId) > 1
        LIMIT ?
    """

    # Relations
    TRACKS_SQL = """
        SELECT trackId, trackNumber, trackCount, trackName, trackTimeMillis,
               artistName, primaryGenreName, releaseDate, previewUrl, artworkUrl,
               trackViewUrl, artistId, collectionId, collectionName, country,
               discCount, discNumber
        FROM track 
        WHERE collectionId = ? 
        ORDER BY trackNumber ASC
    """

    # ========== Conversion Methods ==========

    @staticmethod
    def from_api_item(item: dict) -> tuple:
        """Extract fields from iTunes API response into DB tuple."""
        return (
            item.get("collectionId"),
            item.get("collectionType", ""),
            item.get("collectionName", ""),
            item.get("collectionCensoredName", ""),
            item.get("collectionViewUrl", ""),
            item.get("trackCount", 0),
            item.get("artistId"),
            item.get("artistName", ""),
            item.get("releaseDate", ""),
            item.get("primaryGenreName", ""),
            item.get("artworkUrl100", ""),
            item.get("copyright", ""),
            item.get("country", ""),
        )

    @staticmethod
    def to_api_response(row: tuple) -> dict:
        """Convert full DB row to iTunes-like dict."""
        return {
            "wrapperType": "collection",
            "collectionId": row[0],
            "collectionType": row[1],
            "collectionName": row[2],
            "collectionCensoredName": row[3],
            "collectionViewUrl": row[4],
            "trackCount": row[5],
            "artistId": row[6],
            "artistName": row[7],
            "releaseDate": row[8],
            "primaryGenreName": row[9],
            "artworkUrl100": row[10],
            "copyright": row[11],
            "country": row[12],
        }

    @staticmethod
    def to_search_result(row: tuple) -> dict:
        """Convert search result row to iTunes-like dict."""
        return {
            "wrapperType": "collection",
            "collectionId": row[0],
            "collectionName": row[1],
            "artworkUrl100": row[2],
            "artistName": row[3],
            "collectionViewUrl": row[4],
            "releaseDate": row[5],
            "primaryGenreName": row[6],
            "copyright": row[7],
            "country": row[8],
            "trackCount": row[9],
        }


class CacheSchema:
    TABLE = "cache"
    PK = "cacheId"

    CACHE_GET_SQL = """
        SELECT content FROM cache 
        WHERE cacheId = ?
    """

    CACHE_SET_SQL = """
            UPDATE cache SET content = ? WHERE cacheId = ?
        """

    COLUMNS_DEF = """
        cacheId INTEGER PRIMARY KEY,
        content TEXT
    """

    INSERT_COLUMNS = [
        "cacheId", "content"
    ]
    INSERT_SQL = f"""
        INSERT OR REPLACE INTO cache 
        ({', '.join(INSERT_COLUMNS)})
        VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))})
    """

    @staticmethod
    def from_api_item(item: dict) -> tuple:
        """Extract fields from iTunes API response into DB tuple."""
        return (
            item.get("cacheId"),
            item.get("content")
        )


class TrackSchema:
    """Track table schema, CRUD, search, and relations."""

    TABLE = "track"
    PK = "trackId"

    COLUMNS_DEF = """
        trackId INTEGER PRIMARY KEY,
        trackNumber INTEGER,
        trackCount INTEGER,
        trackName TEXT,
        trackCensoredName TEXT,
        trackTimeMillis INTEGER,
        discCount INTEGER,
        discNumber INTEGER,
        collectionId INTEGER,
        collectionName TEXT,
        collectionCensoredName TEXT,
        artistId INTEGER,
        artistName TEXT,
        primaryGenreName TEXT,
        releaseDate TEXT,
        balePostId INTEGER NOT NULL DEFAULT 0,
        previewUrl TEXT,
        trackViewUrl TEXT,
        artworkUrl TEXT,
        country TEXT,
        FOREIGN KEY (artistId) REFERENCES artist(artistId),
        FOREIGN KEY (collectionId) REFERENCES collection(collectionId)
    """

    INSERT_COLUMNS = [
        "trackId", "trackNumber", "trackCount", "trackName",
        "trackCensoredName", "trackTimeMillis", "discCount", "discNumber",
        "collectionId", "collectionName", "collectionCensoredName",
        "artistId", "artistName", "primaryGenreName", "releaseDate",
        "balePostId", "previewUrl", "trackViewUrl", "artworkUrl", "country"
    ]

    SELECT_COLUMNS = "*"

    INSERT_SQL = f"""
        INSERT OR REPLACE INTO track 
        ({', '.join(INSERT_COLUMNS)})
        VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))})
    """

    GET_BY_ID_SQL = f"SELECT {SELECT_COLUMNS} FROM track WHERE trackId = ?"

    SEARCH_SQL = """
        SELECT trackId, collectionId, trackName, artworkUrl,
               artistName, artistId, primaryGenreName, releaseDate,
               previewUrl, trackViewUrl, trackTimeMillis, country
        FROM track 
        WHERE trackName LIKE ? 
        LIMIT ?
    """

    # ========== Conversion Methods ==========

    @staticmethod
    def from_api_item(item: dict) -> tuple:
        """Extract fields from iTunes API response into DB tuple."""
        return (
            item.get("trackId"),
            item.get("trackNumber", 0),
            item.get("trackCount", 0),
            item.get("trackName", ""),
            item.get("trackCensoredName", ""),
            item.get("trackTimeMillis", 0),
            item.get("discCount", 0),
            item.get("discNumber", 0),
            item.get("collectionId"),
            item.get("collectionName", ""),
            item.get("collectionCensoredName", ""),
            item.get("artistId"),
            item.get("artistName", ""),
            item.get("primaryGenreName", ""),
            item.get("releaseDate", ""),
            item.get("balePostId", 0),
            item.get("previewUrl", ""),
            item.get("trackViewUrl", ""),
            item.get("artworkUrl100", ""),
            item.get("country", ""),
        )

    @staticmethod
    def to_api_response(row: tuple) -> dict:
        """Convert full DB row to iTunes-like dict."""
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
            "balePostId": row[15],
            "previewUrl": row[16],
            "trackViewUrl": row[17],
            "artworkUrl100": row[18],
            "country": row[19],
        }

    @staticmethod
    def to_search_result(row: tuple) -> dict:
        """Convert search result row to iTunes-like dict."""
        return {
            "wrapperType": "track",
            "trackId": row[0],
            "collectionId": row[1],
            "trackName": row[2],
            "artworkUrl100": row[3],
            "artistName": row[4],
            "artistId": row[5],
            "primaryGenreName": row[6],
            "releaseDate": row[7],
            "previewUrl": row[8],
            "trackViewUrl": row[9],
            "trackTimeMillis": row[10],
            "country": row[11],
        }

    @staticmethod
    def to_relation_result(row: tuple) -> dict:
        """Convert relation query row (used by Collection.tracks / Artist.tracks)."""
        return TrackSchema.to_search_result((
            row[0],  # trackId
            row[13],  # collectionId (index adjusted for relation queries)
            row[3],  # trackName
            row[9],  # artworkUrl
            row[5],  # artistName
            row[12],  # artistId
            row[6],  # primaryGenreName
            row[7],  # releaseDate
            row[8],  # previewUrl
            row[11],  # trackViewUrl
            row[4],  # trackTimeMillis
            row[15],  # country
        ))


# Schema registry
SCHEMAS = {
    "artist": ArtistSchema,
    "collection": CollectionSchema,
    "track": TrackSchema,
    "cache": CacheSchema,
}

# Entity aliases
ENTITY_ALIASES = {
    "album": "collection",
    "song": "track",
    "music": "track",
}


# ============================================================================
# Database Class
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
            async with db.execute(CollectionSchema.TRACKS_SQL, (collection_id,)) as cursor:
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
            "trackTimeMillis": row[4],
            "artistName": row[5],
            "primaryGenreName": row[6],
            "releaseDate": row[7],
            "previewUrl": row[8],
            "artworkUrl100": row[9],
            "trackViewUrl": row[10],
            "artistId": row[11],
            "collectionId": row[12],
            "collectionName": row[13],
            "country": row[14],
            "discCount": row[15],
            "discNumber": row[16],
        }


# Add missing static method to ArtistSchema
ArtistSchema.collection_row_to_response = staticmethod(
    lambda row: {
        "wrapperType": "collection",
        "collectionId": row[0],
        "collectionName": row[1],
        "collectionViewUrl": row[2],
        "artworkUrl100": row[3],
        "artistName": row[4],
        "releaseDate": row[5],
        "primaryGenreName": row[6],
        "trackCount": row[7],
        "copyright": row[8],
        "country": row[9],
    }
)

# ============================================================================
# Global Instance & Convenience Functions
# ============================================================================

db = Database()

# --- Insert ---
insert_artist = lambda item: db.insert("artist", item)
insert_collection = lambda item: db.insert("collection", item)
insert_track = lambda item: db.insert("track", item)

# --- Get by ID ---
get_artist_db = lambda artist_id: db.get_by_id("artist", artist_id)
get_collection_db = lambda collection_id: db.get_by_id("collection", collection_id)
get_track_db = lambda track_id: db.get_by_id("track", track_id)

# --- Relations ---
get_artist_tracks = lambda artist_id: db.get_artist_tracks(artist_id)
get_artist_collections = lambda artist_id: db.get_artist_collections(artist_id)
get_collection_tracks = lambda collection_id: db.get_collection_tracks(collection_id)

# --- Cache ---
get_cache = lambda cache_id: db.get_cache(cache_id)
set_cache = lambda item: db.insert("cache", item)

# --- Users ---
insert_user = lambda user_id: db.insert_user(user_id)
get_users_db = lambda user_id: db.get_user_exists(user_id)
get_all_users = lambda: db.get_all_users()

# --- Search ---
local_search = lambda term, entity="all": db.search(term, entity)

# --- Init ---
init_db = lambda: db.init()
