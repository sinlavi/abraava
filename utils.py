# utils.py
import os
import requests
from uuid import uuid4
import logging

def delete_file(path: str):
    if os.path.exists(path):
        os.remove(path)
        logging.info(f"Deleted file: {path}")

def fetch_songlink(url: str):
    try:
        logging.info(f"Fetching Song.link for: {url}")
        r = requests.get("https://api.song.link/v1-alpha.1/links", params={"url": url})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logging.error(f"Song.link fetch error: {e}")
        return None

def extract_itunes(data: dict):
    try:
        platforms = data.get("linksByPlatform", {})
        itunes = platforms.get("itunes", {})
        eid = itunes.get("entityUniqueId")
        return data.get("entitiesByUniqueId", {}).get(eid)
    except Exception as e:
        logging.error(f"Extract iTunes error: {e}")
        return None

def fetch_songlink_priority_url(data: dict):
    platforms = data.get("linksByPlatform", {})
    return platforms.get("soundcloud", {}).get("url") or platforms.get("youtube", {}).get("url")

def format_meta(meta: dict):
    return (
        f"\U0001F3B5 *{meta.get('trackName')}*\n"
        f"\U0001F464 {meta.get('artistName')}\n"
        f"🖼 {meta.get('collectionName')}\n"
        f"📅 {meta.get('releaseDate', '')[:10]}\n"
        f"🎧 {meta.get('primaryGenreName', '-')}"
    )
