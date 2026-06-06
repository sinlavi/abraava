import asyncio
from typing import List, Dict, Any, Optional
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from ytmusicapi import YTMusic
import yt_dlp
from core.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from core.logger import logger

class MusicAdapter:
    def __init__(self):
        self.sp = None
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
                self.sp = spotipy.Spotify(auth_manager=auth_manager)
            except Exception as e:
                logger.error(f"Failed to initialize Spotify: {e}")

        self.ytm = YTMusic()

    def _sp_to_itunes(self, sp_data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        if entity_type == "track":
            album = sp_data.get("album", {})
            return {
                "wrapperType": "track",
                "trackId": f"sp_{sp_data['id']}",
                "trackName": sp_data["name"],
                "artistId": f"sp_{sp_data['artists'][0]['id']}" if sp_data.get("artists") else None,
                "artistName": ", ".join([a["name"] for a in sp_data["artists"]]) if sp_data.get("artists") else "Unknown",
                "collectionId": f"sp_{album['id']}" if album.get("id") else None,
                "collectionName": album.get("name", "Unknown"),
                "artworkUrl100": album["images"][0]["url"] if album.get("images") else None,
                "trackTimeMillis": sp_data.get("duration_ms", 0),
                "releaseDate": album.get("release_date", ""),
                "primaryGenreName": None, # Spotify doesn't provide genre at track level easily
                "trackViewUrl": sp_data["external_urls"].get("spotify"),
                "previewUrl": sp_data.get("preview_url")
            }
        elif entity_type == "album":
            return {
                "wrapperType": "collection",
                "collectionId": f"sp_{sp_data['id']}",
                "collectionName": sp_data["name"],
                "artistId": f"sp_{sp_data['artists'][0]['id']}" if sp_data.get("artists") else None,
                "artistName": ", ".join([a["name"] for a in sp_data["artists"]]) if sp_data.get("artists") else "Unknown",
                "artworkUrl100": sp_data["images"][0]["url"] if sp_data.get("images") else None,
                "trackCount": sp_data.get("total_tracks", 0),
                "releaseDate": sp_data.get("release_date", ""),
                "primaryGenreName": ", ".join(sp_data.get("genres", [])),
                "collectionViewUrl": sp_data["external_urls"].get("spotify")
            }
        elif entity_type == "artist":
            return {
                "wrapperType": "artist",
                "artistId": f"sp_{sp_data['id']}",
                "artistName": sp_data["name"],
                "primaryGenreName": ", ".join(sp_data.get("genres", [])),
                "artistLinkUrl": sp_data["external_urls"].get("spotify"),
                "artworkUrl100": sp_data["images"][0]["url"] if sp_data.get("images") else None
            }
        return sp_data

    def _ytm_to_itunes(self, ytm_data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        if entity_type == "track":
            artists = ytm_data.get("artists", [])
            artist_name = ", ".join([a["name"].replace(" - Topic", "") for a in artists]) if artists else "Unknown"
            album = ytm_data.get("album") or {}
            thumbnails = ytm_data.get("thumbnails", [])
            return {
                "wrapperType": "track",
                "trackId": f"yt_{ytm_data['videoId']}",
                "trackName": ytm_data["title"],
                "artistName": artist_name,
                "collectionName": album.get("name", "Unknown"),
                "artworkUrl100": thumbnails[-1]["url"] if thumbnails else None,
                "trackTimeMillis": ytm_data.get("duration_seconds", 0) * 1000,
                "releaseDate": ytm_data.get("year", ""),
                "trackViewUrl": f"https://music.youtube.com/watch?v={ytm_data['videoId']}"
            }
        elif entity_type == "album":
            thumbnails = ytm_data.get("thumbnails", [])
            artist_name = ytm_data.get("artist", "Unknown").replace(" - Topic", "")
            return {
                "wrapperType": "collection",
                "collectionId": f"yt_{ytm_data['browseId']}",
                "collectionName": ytm_data["title"],
                "artistName": artist_name,
                "artworkUrl100": thumbnails[-1]["url"] if thumbnails else None,
                "releaseDate": ytm_data.get("year", ""),
                "collectionViewUrl": f"https://music.youtube.com/browse/{ytm_data['browseId']}"
            }
        return ytm_data

    def _sc_to_itunes(self, sc_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wrapperType": "track",
            "trackId": f"sc_{sc_data['id']}",
            "trackName": sc_data.get("title", "Unknown"),
            "artistName": sc_data.get("uploader", "Unknown"),
            "artworkUrl100": sc_data.get("thumbnail"),
            "trackTimeMillis": sc_data.get("duration", 0) * 1000,
            "trackViewUrl": sc_data.get("webpage_url") or sc_data.get("url")
        }

    async def search_spotify(self, term: str, entity_type: str = "track", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.sp: return []
        loop = asyncio.get_event_loop()
        try:
            type_map = {"track": "track", "album": "album", "artist": "artist"}
            results = await loop.run_in_executor(None, lambda: self.sp.search(q=term, limit=limit, type=type_map.get(entity_type, "track")))

            items = []
            if entity_type == "track": items = results.get("tracks", {}).get("items", [])
            elif entity_type == "album": items = results.get("albums", {}).get("items", [])
            elif entity_type == "artist": items = results.get("artists", {}).get("items", [])

            return [self._sp_to_itunes(item, entity_type) for item in items]
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return []

    async def search_ytm(self, term: str, entity_type: str = "track", limit: int = 20) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            filter_map = {"track": "songs", "album": "albums", "artist": "artists"}
            results = await loop.run_in_executor(None, lambda: self.ytm.search(term, filter=filter_map.get(entity_type, "songs"), limit=limit))
            return [self._ytm_to_itunes(item, entity_type) for item in results]
        except Exception as e:
            logger.error(f"YTM search error: {e}")
            return []

    async def search_sc(self, term: str, limit: int = 20) -> List[Dict[str, Any]]:
        ydl_opts = {'quiet': True, 'extract_flat': True}
        loop = asyncio.get_event_loop()
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"scsearch{limit}:{term}", download=False))
                if info and 'entries' in info:
                    return [self._sc_to_itunes(entry) for entry in info['entries']]
        except Exception as e:
            logger.error(f"SoundCloud search error: {e}")
        return []

    async def get_sp_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            # Strip prefix if present
            if track_id.startswith("sp_"): track_id = track_id[3:]
            track = await loop.run_in_executor(None, lambda: self.sp.track(track_id))
            return self._sp_to_itunes(track, "track")
        except Exception as e:
            logger.error(f"Spotify get track error: {e}")
            return None

    async def get_sp_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            if album_id.startswith("sp_"): album_id = album_id[3:]
            album = await loop.run_in_executor(None, lambda: self.sp.album(album_id))
            return self._sp_to_itunes(album, "album")
        except Exception as e:
            logger.error(f"Spotify get album error: {e}")
            return None

    async def get_sp_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            if artist_id.startswith("sp_"): artist_id = artist_id[3:]
            artist = await loop.run_in_executor(None, lambda: self.sp.artist(artist_id))
            return self._sp_to_itunes(artist, "artist")
        except Exception as e:
            logger.error(f"Spotify get artist error: {e}")
            return None

    async def get_sp_artist_albums(self, artist_id: str) -> List[Dict[str, Any]]:
        if not self.sp: return []
        loop = asyncio.get_event_loop()
        try:
            if artist_id.startswith("sp_"): artist_id = artist_id[3:]
            results = await loop.run_in_executor(None, lambda: self.sp.artist_albums(artist_id, album_type='album,single'))
            return [self._sp_to_itunes(item, "album") for item in results.get("items", [])]
        except Exception as e:
            logger.error(f"Spotify get artist albums error: {e}")
            return []

    async def get_sp_album_tracks(self, album_id: str) -> List[Dict[str, Any]]:
        if not self.sp: return []
        loop = asyncio.get_event_loop()
        try:
            if album_id.startswith("sp_"): album_id = album_id[3:]
            # Fetch album first to get common metadata like images
            album = await loop.run_in_executor(None, lambda: self.sp.album(album_id))
            images = album.get("images", [])
            album_name = album.get("name")

            results = await loop.run_in_executor(None, lambda: self.sp.album_tracks(album_id))
            tracks = []
            for item in results.get("items", []):
                item["album"] = {"id": album_id, "images": images, "name": album_name}
                tracks.append(self._sp_to_itunes(item, "track"))
            return tracks
        except Exception as e:
            logger.error(f"Spotify get album tracks error: {e}")
            return []

    async def get_yt_track(self, video_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            if video_id.startswith("yt_"): video_id = video_id[3:]
            track = await loop.run_in_executor(None, lambda: self.ytm.get_song(video_id))
            # get_song returns a different format, need to adjust
            video_details = track.get("videoDetails", {})
            return {
                "wrapperType": "track",
                "trackId": f"yt_{video_id}",
                "trackName": video_details.get("title"),
                "artistName": video_details.get("author"),
                "artworkUrl100": video_details.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url"),
                "trackTimeMillis": int(video_details.get("lengthSeconds", 0)) * 1000,
                "trackViewUrl": f"https://music.youtube.com/watch?v={video_id}"
            }
        except Exception as e:
            logger.error(f"YTM get track error: {e}")
            return None

    async def get_sc_track(self, sc_id: str) -> Optional[Dict[str, Any]]:
        # For SoundCloud we might have a numeric ID or a URL slug.
        # Since we use yt-dlp for search, we get the full info there.
        # If we only have the ID, we try to use it with a generic SC URL if it looks like one.
        # However, yt-dlp usually prefers the full URL.
        ydl_opts = {'quiet': True}
        loop = asyncio.get_event_loop()
        try:
            # If it's already a URL, use it. Otherwise, we might be in trouble without the slug.
            # In our search, we store the full URL in the direct links cache.
            # But here we need to return the metadata.
            if sc_id.startswith("sc_"): sc_id = sc_id[3:]

            url = sc_id if sc_id.startswith("http") else f"https://soundcloud.com/{sc_id}"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                return self._sc_to_itunes(info)
        except Exception as e:
            logger.error(f"SC get track error: {e}")
        return None

    async def get_yt_album(self, browse_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            if browse_id.startswith("yt_"): browse_id = browse_id[3:]
            album = await loop.run_in_executor(None, lambda: self.ytm.get_album(browse_id))
            return self._ytm_to_itunes(album, "album")
        except Exception as e:
            logger.error(f"YTM get album error: {e}")
            return None

    async def get_yt_album_tracks(self, browse_id: str) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            if browse_id.startswith("yt_"): browse_id = browse_id[3:]
            album = await loop.run_in_executor(None, lambda: self.ytm.get_album(browse_id))
            tracks = []
            album_name = album.get("title")
            thumbnails = album.get("thumbnails", [])
            for item in album.get("tracks", []):
                # Inject missing info for normalization
                item["album"] = {"name": album_name}
                if not item.get("thumbnails"): item["thumbnails"] = thumbnails
                tracks.append(self._ytm_to_itunes(item, "track"))
            return tracks
        except Exception as e:
            logger.error(f"YTM get album tracks error: {e}")
            return []

    def _it_to_itunes(self, it_data: Dict[str, Any]) -> Dict[str, Any]:
        # Prefix IDs for official iTunes results
        it_data = it_data.copy()
        if "trackId" in it_data: it_data["trackId"] = f"it_{it_data['trackId']}"
        if "collectionId" in it_data: it_data["collectionId"] = f"it_{it_data['collectionId']}"
        if "artistId" in it_data: it_data["artistId"] = f"it_{it_data['artistId']}"
        return it_data

    async def search_itunes_official(self, term: str, entity_type: str = "track", limit: int = 20) -> List[Dict[str, Any]]:
        from crawlers.itunes import search_itunes
        type_map = {"track": "musicTrack", "album": "album", "artist": "musicArtist"}
        entity = type_map.get(entity_type, "musicTrack")

        results = await search_itunes(term, entity=entity, limit=limit, official=True)
        if results and "results" in results:
            return [self._it_to_itunes(item) for item in results["results"]]
        return []
