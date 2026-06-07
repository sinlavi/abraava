import asyncio
import os
import re
import socket
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

import yt_dlp
from ytmusicapi import YTMusic
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from core.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, PROXY
from core.logger import logger
from crawlers.itunes import search_itunes, lookup_itunes

YT_METADATA_METHODS = [1, 2, 3]
SC_METADATA_METHODS = [1, 2]

def _get_cookies_path() -> Optional[str]:
    """Get path to cookies.txt in root folder."""
    script_dir = Path(__file__).parent.parent
    cookies_path = script_dir / "cookies.txt"
    if cookies_path.exists() and cookies_path.is_file():
        return str(cookies_path)
    return None

class MusicAdapter:
    def __init__(self):
        # Initialize Spotify
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
                self.sp = spotipy.Spotify(auth_manager=auth_manager)
            except Exception as e:
                logger.error(f"Failed to initialize Spotify: {e}")
                self.sp = None
        else:
            self.sp = None

        # Initialize YouTube Music
        cookies = _get_cookies_path()
        try:
            self.ytm = YTMusic(auth=cookies) if cookies else YTMusic()
        except Exception as e:
            logger.error(f"Failed to initialize YTMusic: {e}")
            self.ytm = YTMusic()

    def _sp_to_itunes(self, sp_data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        """Normalize Spotify metadata to iTunes-like format."""
        if entity_type == "track":
            album = sp_data.get("album") or {}
            images = album.get("images") or sp_data.get("images") or []
            return {
                "wrapperType": "track",
                "trackId": f"sp_{sp_data['id']}",
                "trackName": sp_data["name"],
                "artistName": ", ".join([a["name"] for a in sp_data["artists"]]),
                "collectionName": album.get("name"),
                "artworkUrl100": images[0]["url"] if images else None,
                "trackTimeMillis": sp_data["duration_ms"],
                "releaseDate": album.get("release_date"),
                "trackViewUrl": sp_data["external_urls"]["spotify"]
            }
        elif entity_type == "album":
            images = sp_data.get("images") or []
            return {
                "wrapperType": "collection",
                "collectionId": f"sp_{sp_data['id']}",
                "collectionName": sp_data["name"],
                "artistName": ", ".join([a["name"] for a in sp_data["artists"]]),
                "artworkUrl100": images[0]["url"] if images else None,
                "trackCount": sp_data.get("total_tracks", 0),
                "releaseDate": sp_data.get("release_date"),
                "collectionViewUrl": sp_data["external_urls"]["spotify"]
            }
        elif entity_type == "artist":
            images = sp_data.get("images") or []
            return {
                "wrapperType": "artist",
                "artistId": f"sp_{sp_data['id']}",
                "artistName": sp_data["name"],
                "primaryGenreName": sp_data.get("genres", [None])[0] if sp_data.get("genres") else None,
                "artworkUrl100": images[0]["url"] if images else None,
                "artistLinkUrl": sp_data["external_urls"]["spotify"]
            }
        return sp_data

    def _ytm_to_itunes(self, ytm_data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        """Normalize YTMusic metadata to iTunes-like format."""
        if entity_type == "track":
            thumbnails = ytm_data.get("thumbnails") or []
            artists = ytm_data.get("artists") or []
            artist_name = ", ".join([a["name"] for a in artists]) if isinstance(artists, list) else "Unknown"
            album = ytm_data.get("album") or {}

            return {
                "wrapperType": "track",
                "trackId": f"yt_{ytm_data.get('videoId')}",
                "trackName": ytm_data.get("title"),
                "artistName": artist_name,
                "collectionName": album.get("name") if isinstance(album, dict) else album,
                "artworkUrl100": thumbnails[-1]["url"] if thumbnails else None,
                "trackTimeMillis": int(ytm_data.get("duration_seconds", 0)) * 1000,
                "trackViewUrl": f"https://music.youtube.com/watch?v={ytm_data.get('videoId')}"
            }
        elif entity_type == "album":
            thumbnails = ytm_data.get("thumbnails") or []
            artists = ytm_data.get("artists") or []
            artist_name = ", ".join([a["name"] for a in artists]) if isinstance(artists, list) else "Unknown"

            return {
                "wrapperType": "collection",
                "collectionId": f"yt_{ytm_data.get('browseId')}",
                "collectionName": ytm_data.get("title"),
                "artistName": artist_name,
                "artworkUrl100": thumbnails[-1]["url"] if thumbnails else None,
                "trackCount": int(ytm_data.get("trackCount") or 0),
                "collectionViewUrl": f"https://music.youtube.com/browse/{ytm_data.get('browseId')}"
            }
        return ytm_data

    def _sc_to_itunes(self, sc_info: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize SoundCloud metadata (from yt-dlp) to iTunes-like format."""
        return {
            "wrapperType": "track",
            "trackId": f"sc_{sc_info.get('id')}",
            "trackName": sc_info.get("title"),
            "artistName": sc_info.get("uploader"),
            "artworkUrl100": sc_info.get("thumbnail"),
            "trackTimeMillis": int(sc_info.get("duration", 0)) * 1000,
            "trackViewUrl": sc_info.get("webpage_url")
        }

    async def get_sp_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
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

    def _get_ydl_opts(self, method, proxy=None):
        opts = {'quiet': True, 'no_check_certificate': True, 'extract_flat': False}
        cookies = _get_cookies_path()
        if cookies: opts['cookiefile'] = cookies

        if method == 2 and proxy:
            opts['proxy'] = proxy
        elif method == 3:
            opts['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
            if proxy: opts['proxy'] = proxy
        return opts

    async def get_yt_track(self, video_id: str) -> Optional[Dict[str, Any]]:
        global YT_METADATA_METHODS
        if video_id.startswith("yt_"): video_id = video_id[3:]
        url = f"https://www.youtube.com/watch?v={video_id}"

        from core.config import PROXY
        proxy = PROXY
        if not proxy:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                if s.connect_ex(("127.0.0.1", 1080)) == 0:
                    proxy = "socks5://127.0.0.1:1080"
            except: pass
            finally: s.close()

        loop = asyncio.get_event_loop()

        for method in list(YT_METADATA_METHODS):
            try:
                opts = self._get_ydl_opts(method, proxy)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info:
                        if method in YT_METADATA_METHODS:
                            YT_METADATA_METHODS.remove(method)
                            YT_METADATA_METHODS.insert(0, method)

                        return {
                            "wrapperType": "track",
                            "trackId": f"yt_{video_id}",
                            "trackName": info.get("title", "Unknown"),
                            "artistName": info.get("uploader", info.get("artist", "Unknown")),
                            "collectionName": info.get("album"),
                            "artworkUrl100": info.get("thumbnail"),
                            "trackTimeMillis": int(info.get("duration", 0)) * 1000,
                            "releaseDate": info.get("upload_date", "")[:4],
                            "trackViewUrl": url
                        }
            except Exception as e:
                logger.debug(f"YT Metadata method {method} failed: {e}")
                if method in YT_METADATA_METHODS:
                    YT_METADATA_METHODS.remove(method)
                    YT_METADATA_METHODS.append(method)

        # Final Fallback to YTM API
        try:
            track = await loop.run_in_executor(None, lambda: self.ytm.get_song(video_id))
            details = track.get("videoDetails", {})
            if details:
                return {
                    "wrapperType": "track",
                    "trackId": f"yt_{video_id}",
                    "trackName": details.get("title"),
                    "artistName": details.get("author"),
                    "artworkUrl100": details.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url"),
                    "trackTimeMillis": int(details.get("lengthSeconds", 0)) * 1000,
                    "trackViewUrl": url
                }
        except: pass
        return None

    async def get_sc_track(self, sc_id: str) -> Optional[Dict[str, Any]]:
        global SC_METADATA_METHODS
        if sc_id.startswith("sc_"): sc_id = sc_id[3:]

        if sc_id.isdigit():
            url = f"https://api.soundcloud.com/tracks/{sc_id}"
        elif sc_id.startswith("http"):
            url = sc_id
        else:
            url = f"https://soundcloud.com/{sc_id}"

        from core.config import PROXY
        proxy = PROXY
        if not proxy:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                if s.connect_ex(("127.0.0.1", 1080)) == 0:
                    proxy = "socks5://127.0.0.1:1080"
            except: pass
            finally: s.close()

        loop = asyncio.get_event_loop()

        for method in list(SC_METADATA_METHODS):
            try:
                opts = {'quiet': True, 'no_check_certificate': True}
                if method == 2 and proxy:
                    opts['proxy'] = proxy

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info:
                        if method in SC_METADATA_METHODS:
                            SC_METADATA_METHODS.remove(method)
                            SC_METADATA_METHODS.insert(0, method)
                        return self._sc_to_itunes(info)
            except Exception as e:
                logger.debug(f"SC Metadata method {method} failed: {e}")
                if method in SC_METADATA_METHODS:
                    SC_METADATA_METHODS.remove(method)
                    SC_METADATA_METHODS.append(method)
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
