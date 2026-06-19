import asyncio
import logging
import random
from typing import Optional, List, Dict, Any

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from ytmusicapi import YTMusic
import yt_dlp

from core.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, PROXY, OFFLINE_MODE
from crawlers.youtube import search_youtube_track

logger = logging.getLogger("ABRAAVA:MUSIC_ADAPTER")

YT_METADATA_METHODS = [1, 2, 3]
SC_METADATA_METHODS = [1, 2]

class MusicAdapter:
    def __init__(self):
        self.sp = None
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                proxies = {"https": PROXY, "http": PROXY} if PROXY else None
                auth_manager = SpotifyClientCredentials(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET,
                    proxies=proxies
                )
                self.sp = spotipy.Spotify(auth_manager=auth_manager, proxies=proxies)
            except Exception as e:
                logger.error(f"Spotify initialization error: {e}")

        proxies = {"https": PROXY, "http": PROXY} if PROXY else None
        self.ytm = YTMusic(proxies=proxies)

    def _get_ydl_opts(self, method, proxy=None):
        opts = {'quiet': True, 'no_check_certificate': True, 'extract_flat': False}
        if PROXY: opts['proxy'] = PROXY
        if method == 3:
            opts['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
        return opts

    async def get_yt_track(self, video_id: str) -> Optional[Dict[str, Any]]:
        global YT_METADATA_METHODS
        logger.info(f"Fetching YouTube metadata for: {video_id}")
        if video_id.startswith("yt_"): video_id = video_id[3:]
        url = f"https://www.youtube.com/watch?v={video_id}"

        loop = asyncio.get_event_loop()
        for method in list(YT_METADATA_METHODS):
            try:
                opts = self._get_ydl_opts(method)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info:
                        if method in YT_METADATA_METHODS:
                            YT_METADATA_METHODS.remove(method)
                            YT_METADATA_METHODS.insert(0, method)

                        result = self._yt_to_itunes(info)
                        if result:
                            from crawlers.itunes import save_metadata
                            await save_metadata(result, "track")
                            return result
            except Exception as e:
                logger.warning(f"YouTube metadata fetch method {method} failed: {e}")
                continue
        return None

    def _yt_to_itunes(self, info: dict) -> dict:
        return {
            "wrapperType": "track",
            "kind": "song",
            "artistName": info.get("uploader", info.get("artist", "Unknown YouTube Artist")),
            "trackName": info.get("title", "Unknown YouTube Track"),
            "collectionName": info.get("album", ""),
            "trackId": f"yt_{info.get('id')}",
            "artworkUrl100": info.get("thumbnail"),
            "trackTimeMillis": int(info.get("duration", 0)) * 1000,
            "releaseDate": info.get("upload_date", ""),
            "primaryGenreName": "YouTube"
        }

    async def get_sc_track(self, sc_id: str) -> Optional[Dict[str, Any]]:
        global SC_METADATA_METHODS
        logger.info(f"Fetching SoundCloud metadata for: {sc_id}")
        if sc_id.startswith("sc_"):
            sc_id = sc_id[3:]
            url = f"https://soundcloud.com/{sc_id}"
        elif sc_id.isdigit():
            url = f"https://api.soundcloud.com/tracks/{sc_id}"
        elif sc_id.startswith("http"):
            url = sc_id
        else:
            url = f"https://soundcloud.com/{sc_id}"

        loop = asyncio.get_event_loop()
        for method in list(SC_METADATA_METHODS):
            try:
                opts = {'quiet': True, 'no_check_certificate': True}
                if PROXY: opts['proxy'] = PROXY

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info:
                        if method in SC_METADATA_METHODS:
                            SC_METADATA_METHODS.remove(method)
                            SC_METADATA_METHODS.insert(0, method)
                        result = self._sc_to_itunes(info)
                        if result:
                            from crawlers.itunes import save_metadata
                            await save_metadata(result, "track")
                            return result
            except Exception as e:
                logger.warning(f"SoundCloud metadata fetch method {method} failed: {e}")
                continue
        return None

    def _sc_to_itunes(self, info: dict) -> dict:
        return {
            "wrapperType": "track",
            "kind": "song",
            "artistName": info.get("uploader", info.get("artist", "Unknown SoundCloud Artist")),
            "trackName": info.get("title", "Unknown SoundCloud Track"),
            "collectionName": info.get("album", ""),
            "trackId": f"sc_{info.get('uploader_id')}/{info.get('display_id')}" if info.get('display_id') else f"sc_{info.get('id')}",
            "artworkUrl100": info.get("thumbnail"),
            "trackTimeMillis": int(info.get("duration", 0)) * 1000,
            "releaseDate": info.get("upload_date", ""),
            "primaryGenreName": "SoundCloud"
        }

    async def search_spotify(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.sp: return []
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, lambda: self.sp.search(q=query, limit=limit, type="track"))
            tracks = []
            for item in results.get("tracks", {}).get("items", []):
                tracks.append(self._sp_to_itunes(item, "track"))
            return tracks
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return []

    async def get_sp_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        if not self.sp: return None
        try:
            if track_id.startswith("sp_"): track_id = track_id[3:]
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(None, lambda: self.sp.track(track_id))
            result = self._sp_to_itunes(item, "track")
            if result:
                from crawlers.itunes import save_metadata
                await save_metadata(result, "track")
            return result
        except Exception as e:
            logger.error(f"Spotify get track error: {e}")
            return None

    def _sp_to_itunes(self, item: dict, type_: str) -> dict:
        album = item.get("album") or {}
        images = album.get("images") or item.get("images") or []
        artwork = images[0].get("url") if images else None

        res = {
            "wrapperType": "track" if type_ == "track" else "collection",
            "kind": "song" if type_ == "track" else None,
            "artistName": ", ".join([a.get("name") for a in item.get("artists", [])]),
            "trackName": item.get("name"),
            "collectionName": album.get("name", ""),
            "trackId": f"sp_{item.get('id')}",
            "collectionId": f"sp_{album.get('id')}" if album.get('id') else None,
            "artworkUrl100": artwork,
            "trackTimeMillis": item.get("duration_ms"),
            "releaseDate": album.get("release_date"),
            "primaryGenreName": "Spotify"
        }
        return res

    async def get_sp_album_tracks(self, album_id: str) -> List[Dict[str, Any]]:
        if not self.sp: return []
        try:
            if album_id.startswith("sp_"): album_id = album_id[3:]
            loop = asyncio.get_event_loop()
            album_info = await loop.run_in_executor(None, lambda: self.sp.album(album_id))
            album_name = album_info.get("name")
            images = album_info.get("images")

            results = await loop.run_in_executor(None, lambda: self.sp.album_tracks(album_id))
            tracks = []
            for item in results.get("items", []):
                item["album"] = {"id": album_id, "images": images, "name": album_name}
                tracks.append(self._sp_to_itunes(item, "track"))
            return tracks
        except Exception as e:
            logger.error(f"Spotify get album tracks error: {e}")
            return []
