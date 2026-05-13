# ============================================================================
# Schema Classes with Full Encapsulation
# ============================================================================
from pathlib import Path

import aiosqlite


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
        previewUrl TEXT,
        trackViewUrl TEXT,
        artworkUrl TEXT,
        country TEXT,
        FOREIGN KEY (artistId) REFERENCES artist(artistId),
        FOREIGN KEY (collectionId) REFERENCES collection(collectionId)
    """

    INSERT_COLUMNS = [
        "trackId",
        "trackNumber",
        "trackCount",
        "trackName",
        "trackCensoredName",
        "trackTimeMillis",
        "discCount",
        "discNumber",
        "collectionId",
        "collectionName",
        "collectionCensoredName",
        "artistId",
        "artistName",
        "primaryGenreName",
        "releaseDate",
        "previewUrl",
        "trackViewUrl",
        "artworkUrl",
        "country"
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
            item.get("previewUrl", ""),
            item.get("trackViewUrl", ""),
            item.get("artworkUrl100", ""),
            item.get("country", ""),
        )

    @staticmethod
    def to_api_response(row: tuple) -> dict:
        """Convert full DB row to iTunes-like dict."""
        return {
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
