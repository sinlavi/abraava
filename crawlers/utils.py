import logging
from typing import Optional, Dict, Any, Union
from balethon.objects import Message
from core.config import OFFLINE_MODE
from crawlers.itunes import lookup_itunes
from services.music_adapter import MusicAdapter
import re

logger = logging.getLogger("ABRAAVA:UTILS")
music_adapter = MusicAdapter()

def format_artist_hashtag(artist_name: str) -> str:
    # Remove special characters and split by space/hyphen
    words = re.split(r'[\s\-_]+', artist_name)
    # Capitalize each word and join (CamelCase)
    camel_case = "".join(word.capitalize() for word in words if word)
    return f"#{camel_case}"

async def get_track(track_id: Union[int, str], status_msg: Message = None) -> Optional[Dict[str, Any]]:
    if OFFLINE_MODE: return None

    if isinstance(track_id, str):
        if track_id.startswith("sp_"):
            track = await music_adapter.get_sp_track(track_id)
            return {"results": [track]} if track else None
        elif track_id.startswith("yt_"):
            track = await music_adapter.get_yt_track(track_id)
            return {"results": [track]} if track else None
        elif track_id.startswith("sc_"):
            track = await music_adapter.get_sc_track(track_id)
            return {"results": [track]} if track else None
        elif track_id.startswith("it_"):
            return await lookup_itunes(track_id[3:], status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آهنگ از آیتیونز رسمی...*", official=True)

    return await lookup_itunes(track_id, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آهنگ از آیتیونز...*")

async def get_or_crawl_artist(artist_id: Union[int, str], status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None

    if isinstance(artist_id, str):
        if artist_id.startswith("sp_"):
            artist = await music_adapter.get_sp_artist(artist_id)
            return {"results": [artist]} if artist else None
        elif artist_id.startswith("it_"):
            return await lookup_itunes(artist_id[3:], bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات هنرمند از آیتیونز رسمی...*", official=True)

    return await lookup_itunes(artist_id, bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات هنرمند...*")

async def get_or_crawl_collection(collection_id: Union[int, str], status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None

    if isinstance(collection_id, str):
        if collection_id.startswith("sp_"):
            album = await music_adapter.get_sp_album(collection_id)
            return {"results": [album]} if album else None
        elif collection_id.startswith("yt_"):
            album = await music_adapter.get_yt_album(collection_id)
            return {"results": [album]} if album else None
        elif collection_id.startswith("it_"):
            return await lookup_itunes(collection_id[3:], bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آلبوم از آیتیونز رسمی...*", official=True)

    return await lookup_itunes(collection_id, bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت اطلاعات آلبوم...*")

async def get_or_crawl_artist_collections(artist_id: Union[int, str], status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None

    if isinstance(artist_id, str):
        if artist_id.startswith("sp_"):
            albums = await music_adapter.get_sp_artist_albums(artist_id)
            return {"results": albums} if albums else None
        elif artist_id.startswith("it_"):
            return await lookup_itunes(artist_id[3:], "album", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آلبوم‌های هنرمند از آیتیونز رسمی...*", official=True)

    return await lookup_itunes(artist_id, "album", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آلبوم‌های هنرمند از آیتیونز...*")

async def get_or_crawl_collection_tracks(collection_id: Union[int, str], status_msg: Optional[Message] = None, force: bool = False):
    if OFFLINE_MODE: return None

    if isinstance(collection_id, str):
        if collection_id.startswith("sp_"):
            tracks = await music_adapter.get_sp_album_tracks(collection_id)
            return {"results": tracks, "resultCount": len(tracks)} if tracks else None
        elif collection_id.startswith("yt_"):
            tracks = await music_adapter.get_yt_album_tracks(collection_id)
            return {"results": tracks, "resultCount": len(tracks)} if tracks else None
        elif collection_id.startswith("it_"):
            data = await lookup_itunes(collection_id[3:], "song", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آهنگ‌های آلبوم از آیتیونز رسمی...*", official=True)
            if data and data.get("results"):
                data["results"] = data["results"][1:]
                data["resultCount"] = len(data["results"])
            return data

    data = await lookup_itunes(collection_id, "song", bypass_cache=force, status_msg=status_msg, status_text="⏳ *در حال دریافت آهنگ‌های آلبوم از آیتیونز...*")
    if data and data.get("results"):
        # Skipping the first entry as it's usually the collection metadata, not a track
        data["results"] = data["results"][1:]
        data["resultCount"] = len(data["results"])
    return data
