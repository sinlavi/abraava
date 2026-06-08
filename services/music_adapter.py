import asyncio
from typing import List, Dict, Any, Optional
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from ytmusicapi import YTMusic
import yt_dlp
from crawlers.itunes import save_track, save_album, save_artist, lookup_itunes
from core.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from core.logger import logger

YT_METADATA_METHODS = [1, 2, 3]
SC_METADATA_METHODS = [1, 2]

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
            artists = ytm_data.get("artists")
            if not artists and "author" in ytm_data:
                artist_name = ytm_data["author"].replace(" - Topic", "")
            elif artists:
                artist_name = ", ".join([a["name"].replace(" - Topic", "") for a in artists])
            else:
                artist_name = "Unknown"

            album = ytm_data.get("album")
            if isinstance(album, dict):
                album_name = album.get("name")
            else:
                album_name = album if album else None

            thumbnails = ytm_data.get("thumbnails", [])
            artwork_url = thumbnails[-1]["url"] if thumbnails else None
            if artwork_url and "w120-h120" in artwork_url:
                artwork_url = artwork_url.replace("w120-h120", "w1000-h1000")

            # Extract videoId properly
            v_id = ytm_data.get('videoId') or ytm_data.get('id')

            duration = ytm_data.get("duration_seconds") or ytm_data.get("duration") or 0
            if isinstance(duration, str):
                # Handle cases where duration might be like "4:24"
                if ":" in duration:
                    parts = duration.split(":")
                    if len(parts) == 2: duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3: duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                else:
                    try: duration = int(duration)
                    except: duration = 0

            return {
                "wrapperType": "track",
                "trackId": f"yt_{v_id}" if v_id else None,
                "trackName": ytm_data.get("title", "Unknown"),
                "artistName": artist_name,
                "collectionName": album_name,
                "artworkUrl100": artwork_url,
                "trackTimeMillis": duration * 1000,
                "releaseDate": str(ytm_data.get("year", "")) if ytm_data.get("year") else None,
                "trackViewUrl": f"https://music.youtube.com/watch?v={v_id}" if v_id else None
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
            "artistName": sc_data.get("uploader", sc_data.get("uploader_id", "Unknown")),
            "artworkUrl100": sc_data.get("thumbnail"),
            "trackTimeMillis": 0, # Duration removed as per request
            "releaseDate": sc_data.get("upload_date", "")[:4] if sc_data.get("upload_date") else None,
            "trackViewUrl": sc_data.get("webpage_url") or sc_data.get("url")
        }

    async def search_spotify(self, term: str, entity_type: str = "track", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.sp:
            logger.warning("Spotify not initialized")
            return []
        loop = asyncio.get_event_loop()
        try:
            type_map = {"track": "track", "album": "album", "artist": "artist"}
            results = await loop.run_in_executor(None, lambda: self.sp.search(q=term, limit=limit, type=type_map.get(entity_type, "track")))

            items = []
            if entity_type == "track": items = results.get("tracks", {}).get("items", [])
            elif entity_type == "album": items = results.get("albums", {}).get("items", [])
            elif entity_type == "artist": items = results.get("artists", {}).get("items", [])

            processed = []
            for item in items:
                it_item = self._sp_to_itunes(item, entity_type)
                it_item["sourceType"] = "spotify"
                it_item["sourceUrl"] = item["external_urls"].get("spotify")
                processed.append(it_item)

                # Save to 3rah
                if entity_type == "track": asyncio.create_task(save_track(it_item))
                elif entity_type == "album": asyncio.create_task(save_album(it_item))
                elif entity_type == "artist": asyncio.create_task(save_artist(it_item))

            return processed
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return []

    async def search_ytm(self, term: str, entity_type: str = "track", limit: int = 20) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            filter_map = {"track": "songs", "album": "albums", "artist": "artists"}
            yt_filter = filter_map.get(entity_type, "songs")

            results = await loop.run_in_executor(None, lambda: self.ytm.search(term, filter=yt_filter, limit=limit))

            # Fallback if filter returned nothing
            if not results:
                results = await loop.run_in_executor(None, lambda: self.ytm.search(term, limit=limit))
                results = [r for r in results if r.get('resultType') in ['video', 'song']] if entity_type == 'track' else results

            processed = []
            for item in results:
                it_item = self._ytm_to_itunes(item, entity_type)
                it_item["sourceType"] = "youtube"
                processed.append(it_item)

                # Save to 3rah
                if entity_type == "track": asyncio.create_task(save_track(it_item))
                elif entity_type == "album": asyncio.create_task(save_album(it_item))
                elif entity_type == "artist": asyncio.create_task(save_artist(it_item))

            return processed
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
                    processed = []
                    for entry in info['entries']:
                        it_item = self._sc_to_itunes(entry)
                        it_item["sourceType"] = "soundcloud"
                        it_item["sourceUrl"] = entry.get("webpage_url") or entry.get("url")
                        processed.append(it_item)
                        asyncio.create_task(save_track(it_item))
                    return processed
        except Exception as e:
            logger.error(f"SoundCloud search error: {e}")
        return []

    async def get_sp_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(track_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            # Strip prefix if present
            orig_id = track_id
            if track_id.startswith("sp_"): track_id = track_id[3:]
            track = await loop.run_in_executor(None, lambda: self.sp.track(track_id))
            it_item = self._sp_to_itunes(track, "track")
            it_item["sourceType"] = "spotify"
            it_item["sourceUrl"] = track["external_urls"].get("spotify")
            asyncio.create_task(save_track(it_item))
            return it_item
        except Exception as e:
            logger.error(f"Spotify get track error: {e}")
            return None

    async def get_sp_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(album_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            if album_id.startswith("sp_"): album_id = album_id[3:]
            album = await loop.run_in_executor(None, lambda: self.sp.album(album_id))
            it_item = self._sp_to_itunes(album, "album")
            it_item["sourceType"] = "spotify"
            it_item["sourceUrl"] = album["external_urls"].get("spotify")
            asyncio.create_task(save_album(it_item))
            return it_item
        except Exception as e:
            logger.error(f"Spotify get album error: {e}")
            return None

    async def get_sp_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(artist_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        if not self.sp: return None
        loop = asyncio.get_event_loop()
        try:
            if artist_id.startswith("sp_"): artist_id = artist_id[3:]
            artist = await loop.run_in_executor(None, lambda: self.sp.artist(artist_id))
            it_item = self._sp_to_itunes(artist, "artist")
            it_item["sourceType"] = "spotify"
            it_item["sourceUrl"] = artist["external_urls"].get("spotify")
            asyncio.create_task(save_artist(it_item))
            return it_item
        except Exception as e:
            logger.error(f"Spotify get artist error: {e}")
            return None

    async def get_sp_artist_albums(self, artist_id: str) -> List[Dict[str, Any]]:
        if not self.sp: return []
        loop = asyncio.get_event_loop()
        try:
            if artist_id.startswith("sp_"): artist_id = artist_id[3:]
            results = await loop.run_in_executor(None, lambda: self.sp.artist_albums(artist_id, album_type='album,single'))
            processed = []
            for item in results.get("items", []):
                it_item = self._sp_to_itunes(item, "album")
                it_item["sourceType"] = "spotify"
                it_item["sourceUrl"] = item["external_urls"].get("spotify")
                processed.append(it_item)
                asyncio.create_task(save_album(it_item))
            return processed
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
                it_item = self._sp_to_itunes(item, "track")
                it_item["sourceType"] = "spotify"
                it_item["sourceUrl"] = item["external_urls"].get("spotify")
                tracks.append(it_item)
                asyncio.create_task(save_track(it_item))
            return tracks
        except Exception as e:
            logger.error(f"Spotify get album tracks error: {e}")
            return []

    def _get_ydl_opts(self, method, proxy=None):
        opts = {'quiet': True, 'no_check_certificate': True, 'extract_flat': False}
        if method == 2 and proxy:
            opts['proxy'] = proxy
        elif method == 3:
            opts['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
            if proxy: opts['proxy'] = proxy
        return opts

    async def get_yt_track(self, video_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(video_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        global YT_METADATA_METHODS
        orig_video_id = video_id
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

                        it_item = {
                            "wrapperType": "track",
                            "trackId": f"yt_{video_id}",
                            "trackName": info.get("title", "Unknown"),
                            "artistName": info.get("uploader", info.get("artist", "Unknown")),
                            "collectionName": info.get("album"),
                            "artworkUrl100": info.get("thumbnail"),
                            "trackTimeMillis": int(info.get("duration", 0)) * 1000,
                            "releaseDate": info.get("upload_date", "")[:4],
                            "trackViewUrl": url,
                            "sourceType": "youtube",
                            "sourceUrl": url
                        }
                        asyncio.create_task(save_track(it_item))
                        return it_item
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
                it_item = {
                    "wrapperType": "track",
                    "trackId": f"yt_{video_id}",
                    "trackName": details.get("title"),
                    "artistName": details.get("author"),
                    "artworkUrl100": details.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url"),
                    "trackTimeMillis": int(details.get("lengthSeconds", 0)) * 1000,
                    "trackViewUrl": url,
                    "sourceType": "youtube",
                    "sourceUrl": url
                }
                asyncio.create_task(save_track(it_item))
                return it_item
        except: pass
        return None

    async def get_sc_track(self, sc_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(sc_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        global SC_METADATA_METHODS
        orig_sc_id = sc_id
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
                        it_item = self._sc_to_itunes(info)
                        it_item["sourceType"] = "soundcloud"
                        it_item["sourceUrl"] = info.get("webpage_url") or info.get("url")
                        asyncio.create_task(save_track(it_item))
                        return it_item
            except Exception as e:
                logger.debug(f"SC Metadata method {method} failed: {e}")
                if method in SC_METADATA_METHODS:
                    SC_METADATA_METHODS.remove(method)
                    SC_METADATA_METHODS.append(method)
        return None

    async def get_yt_album(self, browse_id: str) -> Optional[Dict[str, Any]]:
        # Check 3rah first
        cached = await lookup_itunes(browse_id)
        if cached and cached.get("results"):
            return cached["results"][0]

        loop = asyncio.get_event_loop()
        try:
            orig_browse_id = browse_id
            if browse_id.startswith("yt_"): browse_id = browse_id[3:]
            album = await loop.run_in_executor(None, lambda: self.ytm.get_album(browse_id))
            it_item = self._ytm_to_itunes(album, "album")
            it_item["sourceType"] = "youtube"
            it_item["sourceUrl"] = f"https://music.youtube.com/browse/{browse_id}"
            asyncio.create_task(save_album(it_item))
            return it_item
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
                it_item = self._ytm_to_itunes(item, "track")
                it_item["sourceType"] = "youtube"
                it_item["sourceUrl"] = f"https://music.youtube.com/watch?v={item.get('videoId')}"
                tracks.append(it_item)
                asyncio.create_task(save_track(it_item))
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
            processed = []
            for item in results["results"]:
                it_item = self._it_to_itunes(item)
                it_item["sourceType"] = "itunes"
                processed.append(it_item)

                # Save to 3rah
                if entity_type == "track": asyncio.create_task(save_track(it_item))
                elif entity_type == "album": asyncio.create_task(save_album(it_item))
                elif entity_type == "artist": asyncio.create_task(save_artist(it_item))
            return processed
        return []
