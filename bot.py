#!/usr/bin/env python3
"""
Abraava Music Bot – Clean, Modular, Anti‑Sanction YouTube Music Downloader
Features: iTunes crawling, 8‑method yt‑dlp, ID3 tagging, SQLite caching, Bale integration
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiohttp
import aiosqlite
from bale import Bot, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, error
from ytmusicapi import YTMusic

# ---------- Import your 8‑method downloader ----------
from youtube_downloader import download_audio

# ---------- Configuration ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "1011430416:5JY8CU9nGwYtVz0ahfDEIkJyCkVTUCAhLXQ")
DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID")          # optional channel ID for caching audio
DB_PATH = Path("cache.db")
ITEMS_PER_PAGE = 10
FOOTER = "\n\n@abraava_bot\n@abraava"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger("AbraavaBot")

# ---------- Async SQLite Cache Manager ----------
class CacheManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    last_updated INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audio_cache (
                    track_id INTEGER PRIMARY KEY,
                    channel_message_id INTEGER NOT NULL
                )
            """)
            await db.commit()

    async def get(self, cache_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT data FROM cache WHERE id = ?", (cache_id,)) as cur:
                row = await cur.fetchone()
                return json.loads(row[0]) if row else None

    async def set(self, cache_id: str, type_: str, data: Dict[str, Any]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO cache (id, type, data, last_updated) VALUES (?, ?, ?, ?)",
                (cache_id, type_, json.dumps(data), int(time.time()))
            )
            await db.commit()

    async def delete(self, cache_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cache WHERE id = ?", (cache_id,))
            await db.commit()

    async def exists(self, cache_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM cache WHERE id = ?", (cache_id,)) as cur:
                return await cur.fetchone() is not None

    # Audio cache (track_id -> channel message id)
    async def get_audio(self, track_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT channel_message_id FROM audio_cache WHERE track_id = ?", (track_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_audio(self, track_id: int, msg_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT OR REPLACE INTO audio_cache (track_id, channel_message_id) VALUES (?, ?)",
                             (track_id, msg_id))
            await db.commit()

# ---------- iTunes API Client (with auto‑crawling) ----------
class iTunesClient:
    BASE_URL = "https://itunes.apple.com"

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session: Optional[aiohttp.ClientSession] = None

    async def _request(self, endpoint: str, params: dict) -> Optional[Dict]:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            async with self.session.get(url, params=params, ssl=False) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"iTunes {endpoint} -> {resp.status}")
        except Exception as e:
            logger.error(f"iTunes request error: {e}")
        return None

    async def search(self, term: str, entity: Optional[str] = None, limit: int = 50) -> Dict:
        params = {"term": term, "media": "music", "limit": limit, "country": "US"}
        if entity:
            params["entity"] = entity
        result = await self._request("search", params)
        return result or {"resultCount": 0, "results": []}

    async def lookup(self, id: int, entity: Optional[str] = None) -> Dict:
        params = {"id": id, "country": "US"}
        if entity:
            params["entity"] = entity
        result = await self._request("lookup", params)
        return result or {"resultCount": 0, "results": []}

    # ----- Cached getters with automatic crawling -----
    async def get_artist(self, artist_id: int, status_msg: Message = None) -> Optional[Dict]:
        cache_id = f"artist:{artist_id}"
        cached = await self.cache.get(cache_id)
        if cached:
            return cached
        if status_msg:
            await self._safe_edit(status_msg, "⏳ دریافت اطلاعات هنرمند...")
        data = await self.lookup(artist_id)
        if data.get("results"):
            await self.cache.set(cache_id, "artist", data)
            await self._crawl_artist_albums(artist_id, status_msg)
            return data
        return None

    async def _crawl_artist_albums(self, artist_id: int, status_msg: Message = None):
        cache_id = f"artist_albums:{artist_id}"
        if await self.cache.exists(cache_id):
            return
        if status_msg:
            await self._safe_edit(status_msg, "⏳ دریافت آلبوم‌های هنرمند...")
        data = await self.lookup(artist_id, "album")
        albums = []
        for item in data.get("results", []):
            if item.get("wrapperType") == "collection" and item.get("collectionType") == "Album":
                album_id = item["collectionId"]
                albums.append(album_id)
                # cache each album individually
                if not await self.cache.exists(f"album:{album_id}"):
                    await self.cache.set(f"album:{album_id}", "album", {"resultCount": 1, "results": [item]})
                await self._crawl_album_tracks(album_id, status_msg)
        await self.cache.set(cache_id, "artist_albums", {"albums": albums})

    async def get_album(self, album_id: int, status_msg: Message = None) -> Optional[Dict]:
        cache_id = f"album:{album_id}"
        cached = await self.cache.get(cache_id)
        if cached:
            return cached
        if status_msg:
            await self._safe_edit(status_msg, "⏳ دریافت اطلاعات آلبوم...")
        data = await self.lookup(album_id)
        if data.get("results"):
            await self.cache.set(cache_id, "album", data)
            await self._crawl_album_tracks(album_id, status_msg)
            return data
        return None

    async def _crawl_album_tracks(self, album_id: int, status_msg: Message = None):
        cache_id = f"album_tracks:{album_id}"
        if await self.cache.exists(cache_id):
            return
        if status_msg:
            await self._safe_edit(status_msg, "⏳ دریافت آهنگ‌های آلبوم...")
        data = await self.lookup(album_id, "song")
        tracks = []
        for item in data.get("results", []):
            if item.get("wrapperType") == "track" and item.get("kind") == "song":
                track_id = item["trackId"]
                tracks.append(track_id)
                if not await self.cache.exists(f"track:{track_id}"):
                    await self.cache.set(f"track:{track_id}", "track", {"resultCount": 1, "results": [item]})
        await self.cache.set(cache_id, "album_tracks", {"tracks": tracks})

    async def get_track(self, track_id: int, status_msg: Message = None) -> Optional[Dict]:
        cache_id = f"track:{track_id}"
        cached = await self.cache.get(cache_id)
        if cached:
            return cached
        if status_msg:
            await self._safe_edit(status_msg, "⏳ دریافت اطلاعات آهنگ...")
        data = await self.lookup(track_id)
        if data.get("results"):
            await self.cache.set(cache_id, "track", data)
            return data
        return None

    async def get_artist_albums(self, artist_id: int) -> List[Dict]:
        cache_id = f"artist_albums:{artist_id}"
        data = await self.cache.get(cache_id)
        if not data:
            return []
        albums = []
        for album_id in data.get("albums", []):
            album_data = await self.cache.get(f"album:{album_id}")
            if album_data and album_data.get("results"):
                albums.append(album_data["results"][0])
        return albums

    async def get_album_tracks(self, album_id: int) -> List[Dict]:
        cache_id = f"album_tracks:{album_id}"
        data = await self.cache.get(cache_id)
        if not data:
            return []
        tracks = []
        for track_id in data.get("tracks", []):
            track_data = await self.cache.get(f"track:{track_id}")
            if track_data and track_data.get("results"):
                tracks.append(track_data["results"][0])
        return tracks

    @staticmethod
    async def _safe_edit(msg: Message, text: str):
        try:
            await msg.edit(text + FOOTER)
        except:
            pass

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

# ---------- YouTube Music Helper ----------
class YouTubeHelper:
    def __init__(self):
        self.ytmusic = None

    def _get_ytmusic(self):
        if self.ytmusic is None:
            self.ytmusic = YTMusic()
        return self.ytmusic

    async def search_track(self, query: str) -> Optional[str]:
        """Return best videoId for the query."""
        try:
            results = self._get_ytmusic().search(query, filter="songs", limit=1)
            if results and isinstance(results, list) and len(results) > 0:
                return results[0].get("videoId")
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
        return None

# ---------- ID3 Tagger ----------
def tag_mp3(file_path: Path, title: str, artist: str, album: str, cover_bytes: bytes):
    try:
        try:
            audio = ID3(file_path)
        except error:
            audio = ID3()
        audio.add(TIT2(encoding=3, text=title))
        audio.add(TPE1(encoding=3, text=artist))
        if album:
            audio.add(TALB(encoding=3, text=album))
        if cover_bytes:
            audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=cover_bytes))
        audio.save(file_path, v2_version=3)
        logger.info(f"Tagged: {title}")
    except Exception as e:
        logger.error(f"Tagging failed: {e}")

# ---------- Bale Bot Handlers ----------
class AbraavaBot:
    def __init__(self, token: str, cache: CacheManager, itunes: iTunesClient, yt: YouTubeHelper):
        self.bot = Bot(token=token)
        self.cache = cache
        self.itunes = itunes
        self.yt = yt

    async def start(self):
        @self.bot.event
        async def on_ready():
            logger.info(f"{self.bot.user.username} (Abraava) is ready!")
            await self.bot.delete_webhook()
            await self.cache.init()

        @self.bot.event
        async def on_message(message: Message):
            if not message.content:
                return
            is_group = message.chat.type in ["group", "supergroup", "channel"]
            msg_text = message.content

            if is_group:
                if f"@{self.bot.user.username}" not in msg_text:
                    return
                msg_text = msg_text.replace(f"@{self.bot.user.username}", "").strip()

            if msg_text.startswith("/start"):
                await message.reply(
                    f"🎵 **به ربات {BOT_NAME} خوش آمدید!**\n\n"
                    "**دستورات:**\n"
                    "`/search artist:<نام>` – جستجوی هنرمند\n"
                    "`/search album:<نام>` – جستجوی آلبوم\n"
                    "`/search track:<نام>` – جستجوی آهنگ\n"
                    "`/search <نام>` – جستجوی ترکیبی\n\n"
                    "**ویژگی‌ها:**\n"
                    "• کش هوشمند (ارسال فوری)\n"
                    "• متادیتا (کاور، نام، خواننده)\n"
                    "• پخش پیش‌نمایش صوتی\n"
                    "• دانلود MP3 320kbps با ۸ روش ضدتحریم"
                    f"{FOOTER}"
                )
            elif msg_text.startswith("/search"):
                parts = msg_text.split(" ", 1)
                if len(parts) < 2:
                    await message.reply(f"❌ عبارت جستجو را وارد کنید.\nمثال: `/search artist:Taylor Swift`{FOOTER}")
                    return
                query = parts[1].strip()
                if ":" in query:
                    typ, term = query.split(":", 1)
                    typ = typ.lower()
                    if typ not in ("artist", "album", "track"):
                        await message.reply(f"❌ نوع نامعتبر. از artist/album/track استفاده کنید.{FOOTER}")
                        return
                else:
                    typ, term = "all", query

                status_msg = await message.reply(f"🔍 جستجوی {term} ...{FOOTER}")
                entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
                results = await self.itunes.search(term, entity_map.get(typ), limit=50)
                if results.get("resultCount", 0) == 0:
                    await status_msg.edit(f"❌ نتیجه‌ای برای '{term}' یافت نشد.{FOOTER}")
                    return

                search_id = hashlib.md5(f"{typ}:{term}".encode()).hexdigest()[:10]
                await self.cache.set(f"search:{search_id}", "search",
                                     {"type": typ, "term": term, "data": results})
                await status_msg.delete()
                await self._send_search_page(message.chat.id, search_id, 1)

            elif msg_text.startswith("/help"):
                await message.reply(f"🛠 راهنما: از /search استفاده کنید.{FOOTER}")
            elif msg_text.startswith("/about"):
                await message.reply(f"ℹ️ ربات {BOT_NAME} – دانلود موسیقی با کیفیت بالا.{FOOTER}")

        @self.bot.event
        async def on_callback(callback: CallbackQuery):
            data = callback.data
            chat_id = callback.message.chat.id
            if data == "ignore":
                return
            if data == "new_search":
                await callback.message.reply(f"🔍 لطفاً با `/search` جستجو کنید.{FOOTER}")
                return

            parts = data.split(":")
            # Pagination for search results
            if data.startswith("page:search:"):
                search_id = parts[2]
                page = int(parts[3])
                await self._send_search_page(chat_id, search_id, page, callback.message)
            # Pagination for artist
            elif data.startswith("artist:"):
                artist_id = int(parts[1])
                page = int(parts[2]) if len(parts) > 2 else 1
                await self._show_artist(chat_id, artist_id, page, callback.message)
            # Pagination for album
            elif data.startswith("album:"):
                album_id = int(parts[1])
                page = int(parts[2]) if len(parts) > 2 else 1
                await self._show_album(chat_id, album_id, page, callback.message)
            # Show single track
            elif data.startswith("track:"):
                track_id = int(parts[1])
                await self._show_track(chat_id, track_id)
            # Download track
            elif data.startswith("download:"):
                track_id = int(parts[1])
                await self._send_audio_file(chat_id, track_id)
            # Preview track
            elif data.startswith("preview:"):
                track_id = int(parts[1])
                await self._send_preview(chat_id, track_id)
            # Recrawl artist/album/track
            elif data.startswith("recrawl:"):
                typ = parts[1]
                id_ = int(parts[2])
                await self.cache.delete(f"{typ}:{id_}")
                if typ == "artist":
                    await self.cache.delete(f"artist_albums:{id_}")
                    await self._show_artist(chat_id, id_, 1, callback.message)
                elif typ == "album":
                    await self.cache.delete(f"album_tracks:{id_}")
                    await self._show_album(chat_id, id_, 1, callback.message)
                elif typ == "track":
                    await self._show_track(chat_id, id_, callback.message)
            # Show all tracks of an artist (new search)
            elif data.startswith("artist_tracks:"):
                artist_id = int(parts[1])
                page = int(parts[2]) if len(parts) > 2 else 1
                artist_data = await self.itunes.get_artist(artist_id)
                if not artist_data:
                    await self.bot.send_message(chat_id, f"❌ هنرمند یافت نشد.{FOOTER}")
                    return
                artist_name = artist_data["results"][0]["artistName"]
                results = await self.itunes.search(artist_name, "musicTrack", 50)
                if results.get("resultCount", 0) == 0:
                    await self.bot.send_message(chat_id, f"❌ آهنگی یافت نشد.{FOOTER}")
                    return
                search_id = hashlib.md5(f"track:{artist_name}".encode()).hexdigest()[:10]
                await self.cache.set(f"search:{search_id}", "search",
                                     {"type": "track", "term": artist_name, "data": results})
                await self._send_search_page(chat_id, search_id, page, callback.message)
            # Search refinement buttons (from search results)
            elif data.startswith("refine:"):
                _, typ, search_id, page = data.split(":")
                page = int(page)
                cache_data = await self.cache.get(f"search:{search_id}")
                if not cache_data:
                    return
                term = cache_data["term"]
                entity_map = {"artist": "musicArtist", "album": "album", "track": "musicTrack"}
                new_results = await self.itunes.search(term, entity_map.get(typ), 50)
                if new_results.get("resultCount", 0) == 0:
                    await callback.answer(f"هیچ {typ}ای یافت نشد.", show_alert=True)
                    return
                new_search_id = hashlib.md5(f"{typ}:{term}".encode()).hexdigest()[:10]
                await self.cache.set(f"search:{new_search_id}", "search",
                                     {"type": typ, "term": term, "data": new_results})
                await self._send_search_page(chat_id, new_search_id, 1, callback.message)

        self.bot.run()

    # ---------- UI Helpers ----------
    async def _send_search_page(self, chat_id: int, search_id: str, page: int, msg_to_edit: Message = None):
        cache_data = await self.cache.get(f"search:{search_id}")
        if not cache_data:
            text = "❌ نتایج منقضی شد. لطفاً دوباره جستجو کنید." + FOOTER
            if msg_to_edit:
                await msg_to_edit.edit(text)
            else:
                await self.bot.send_message(chat_id, text)
            return

        typ = cache_data["type"]
        term = cache_data["term"]
        results = cache_data["data"]["results"]
        total = len(results)
        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(1, min(page, total_pages))
        start = (page - 1) * ITEMS_PER_PAGE
        page_items = results[start:start + ITEMS_PER_PAGE]

        markup = InlineKeyboardMarkup()
        # Items
        for item in page_items:
            if typ == "all":
                if item.get("wrapperType") == "artist":
                    text = f"🎤 {item['artistName'][:45]}"
                    cb = f"artist:{item['artistId']}:1"
                elif item.get("wrapperType") == "collection":
                    text = f"📀 {item['collectionName'][:45]}"
                    cb = f"album:{item['collectionId']}:1"
                elif item.get("wrapperType") == "track":
                    text = f"🎵 {item['trackName'][:45]}"
                    cb = f"track:{item['trackId']}"
                else:
                    continue
            else:
                if typ == "artist":
                    text = f"🎤 {item['artistName'][:45]}"
                    cb = f"artist:{item['artistId']}:1"
                elif typ == "album":
                    text = f"📀 {item['collectionName'][:45]}"
                    cb = f"album:{item['collectionId']}:1"
                else:  # track
                    text = f"🎵 {item['trackName'][:45]}"
                    cb = f"track:{item['trackId']}"
            markup.add(InlineKeyboardButton(text=text, callback_data=cb))

        # Pagination row
        if total_pages > 1:
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"page:search:{search_id}:{page-1}"))
            row.append(InlineKeyboardButton(f"صفحه {page} از {total_pages}", callback_data="ignore"))
            if page < total_pages:
                row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"page:search:{search_id}:{page+1}"))
            markup.add(*row)

        # Search refinement buttons (only when typ == "all" or we show all three)
        refine_row = []
        if typ == "all" or typ != "artist":
            refine_row.append(InlineKeyboardButton("🎤 جستجو در هنرمندان", callback_data=f"refine:artist:{search_id}:{page}"))
        if typ == "all" or typ != "album":
            refine_row.append(InlineKeyboardButton("📀 جستجو در آلبوم‌ها", callback_data=f"refine:album:{search_id}:{page}"))
        if typ == "all" or typ != "track":
            refine_row.append(InlineKeyboardButton("🎵 جستجو در آهنگ‌ها", callback_data=f"refine:track:{search_id}:{page}"))
        if refine_row:
            markup.add(*refine_row)

        markup.add(InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search"))

        header = f"📋 نتایج جستجو برای '{term}' – {total} مورد" + FOOTER
        if msg_to_edit:
            await msg_to_edit.edit(header, components=markup)
        else:
            await self.bot.send_message(chat_id, header, components=markup)

    async def _show_artist(self, chat_id: int, artist_id: int, page: int, msg_to_edit: Message = None):
        status_msg = await self.bot.send_message(chat_id, f"🔄 در حال پردازش هنرمند...{FOOTER}")
        data = await self.itunes.get_artist(artist_id, status_msg)
        if not data:
            await status_msg.edit(f"❌ هنرمند یافت نشد.{FOOTER}")
            return
        artist = data["results"][0]
        text = f"*🎤 هنرمند:* {artist['artistName']}\n*🎭 سبک:* {artist.get('primaryGenreName', 'نامشخص')}\n"
        if artist.get("artistLinkUrl"):
            text += f"[🔗 لینک آیتونز]({artist['artistLinkUrl']})\n"

        albums = await self.itunes.get_artist_albums(artist_id)
        markup = InlineKeyboardMarkup()
        if albums:
            total = len(albums)
            total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            start = (page - 1) * ITEMS_PER_PAGE
            page_albums = albums[start:start + ITEMS_PER_PAGE]
            text += f"\n*📀 آلبوم‌ها ({total}):*\n"
            for i, alb in enumerate(page_albums, 1):
                btn = InlineKeyboardButton(f"📀 {alb['collectionName'][:45]}", callback_data=f"album:{alb['collectionId']}:1")
                markup.add(btn, row=i)
            if total_pages > 1:
                row = []
                if page > 1:
                    row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"artist:{artist_id}:{page-1}"))
                row.append(InlineKeyboardButton(f"صفحه {page} از {total_pages}", callback_data="ignore"))
                if page < total_pages:
                    row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"artist:{artist_id}:{page+1}"))
                markup.add(*row, row=len(page_albums)+1)
            bottom_row = len(page_albums) + 2
        else:
            bottom_row = 1

        markup.add(InlineKeyboardButton("🎵 آهنگ‌های هنرمند", callback_data=f"artist_tracks:{artist_id}:1"), row=bottom_row)
        markup.add(InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:artist:{artist_id}"), row=bottom_row+1)
        markup.add(InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row+2)

        text += FOOTER
        await status_msg.delete()
        if msg_to_edit:
            await msg_to_edit.edit(text, components=markup)
        else:
            await self.bot.send_message(chat_id, text, components=markup)

    async def _show_album(self, chat_id: int, album_id: int, page: int, msg_to_edit: Message = None):
        status_msg = await self.bot.send_message(chat_id, f"🔄 در حال پردازش آلبوم...{FOOTER}")
        data = await self.itunes.get_album(album_id, status_msg)
        if not data:
            await status_msg.edit(f"❌ آلبوم یافت نشد.{FOOTER}")
            return
        album = data["results"][0]
        release = album.get('releaseDate', 'نامشخص')[:10]
        text = f"*📀 آلبوم:* {album['collectionName']}\n*🎤 هنرمند:* {album['artistName']}\n*📅 انتشار:* {release}\n*🎭 سبک:* {album.get('primaryGenreName', 'نامشخص')}\n"
        if album.get("collectionViewUrl"):
            text += f"[🔗 لینک آیتونز]({album['collectionViewUrl']})\n"

        tracks = await self.itunes.get_album_tracks(album_id)
        markup = InlineKeyboardMarkup()
        if tracks:
            total = len(tracks)
            total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            start = (page - 1) * ITEMS_PER_PAGE
            page_tracks = tracks[start:start + ITEMS_PER_PAGE]
            text += f"\n*🎵 قطعات ({total}):*\n"
            for i, tr in enumerate(page_tracks, start+1):
                dur = self._format_duration(tr.get('trackTimeMillis'))
                text += f"`{i}.` {tr['trackName']} ({dur})\n"
            for tr in page_tracks:
                markup.add(InlineKeyboardButton(f"🎵 {tr['trackName'][:40]}", callback_data=f"track:{tr['trackId']}"))
            if total_pages > 1:
                row = []
                if page > 1:
                    row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"album:{album_id}:{page-1}"))
                row.append(InlineKeyboardButton(f"صفحه {page} از {total_pages}", callback_data="ignore"))
                if page < total_pages:
                    row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"album:{album_id}:{page+1}"))
                markup.add(*row, row=len(page_tracks)+1)
            bottom_row = len(page_tracks) + 2
        else:
            bottom_row = 1

        if album.get("artistId"):
            markup.add(InlineKeyboardButton("🎤 مشاهده هنرمند", callback_data=f"artist:{album['artistId']}:1"), row=bottom_row)
            bottom_row += 1
        markup.add(InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:album:{album_id}"), row=bottom_row)
        markup.add(InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search"), row=bottom_row+1)

        text += FOOTER
        await status_msg.delete()
        # Send album art if available
        artwork = self._high_res_artwork(album.get("artworkUrl100"))
        if artwork:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(artwork) as resp:
                        if resp.status == 200:
                            img = await resp.read()
                            if msg_to_edit:
                                await msg_to_edit.delete()
                            await self.bot.send_photo(chat_id, InputFile(img, "cover.jpg"), caption=text, components=markup)
                            return
            except Exception as e:
                logger.error(f"Album art failed: {e}")
        # Fallback to text only
        if msg_to_edit:
            await msg_to_edit.edit(text, components=markup)
        else:
            await self.bot.send_message(chat_id, text, components=markup)

    async def _show_track(self, chat_id: int, track_id: int, msg_to_edit: Message = None):
        status_msg = await self.bot.send_message(chat_id, f"🔄 در حال بارگذاری آهنگ...{FOOTER}")
        data = await self.itunes.get_track(track_id, status_msg)
        if not data:
            await status_msg.edit(f"❌ آهنگ یافت نشد.{FOOTER}")
            return
        track = data["results"][0]
        dur = self._format_duration(track.get('trackTimeMillis'))
        release = track.get('releaseDate', 'نامشخص')[:10]
        text = f"*🎵 آهنگ:* {track['trackName']}\n*🎤 هنرمند:* {track['artistName']}\n*📀 آلبوم:* {track.get('collectionName', 'نامشخص')}\n*⏱️ مدت:* {dur}\n*🎭 سبک:* {track.get('primaryGenreName', 'نامشخص')}\n*📅 انتشار:* {release}\n"
        if track.get("trackViewUrl"):
            text += f"[🔗 لینک آیتونز]({track['trackViewUrl']})\n"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⬇️ دانلود (320kbps)", callback_data=f"download:{track_id}"), row=1)
        row = 2
        if track.get("previewUrl"):
            markup.add(InlineKeyboardButton("🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"), row=row)
            row += 1
        if track.get('collectionId'):
            markup.add(InlineKeyboardButton("📀 مشاهده آلبوم", callback_data=f"album:{track['collectionId']}:1"), row=row)
            row += 1
        if track.get('artistId'):
            markup.add(InlineKeyboardButton("🎤 مشاهده هنرمند", callback_data=f"artist:{track['artistId']}:1"), row=row)
            row += 1
        markup.add(InlineKeyboardButton("🔄 تازه‌سازی", callback_data=f"recrawl:track:{track_id}"), row=row)
        markup.add(InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search"), row=row+1)

        text += FOOTER
        await status_msg.delete()
        artwork = self._high_res_artwork(track.get("artworkUrl100"))
        if artwork:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(artwork) as resp:
                        if resp.status == 200:
                            img = await resp.read()
                            if msg_to_edit:
                                await msg_to_edit.delete()
                            await self.bot.send_photo(chat_id, InputFile(img, "cover.jpg"), caption=text, components=markup)
                            return
            except Exception as e:
                logger.error(f"Track art failed: {e}")
        if msg_to_edit:
            await msg_to_edit.edit(text, components=markup)
        else:
            await self.bot.send_message(chat_id, text, components=markup)

    # ---------- Download & Preview ----------
    async def _send_audio_file(self, chat_id: int, track_id: int):
        status_msg = await self.bot.send_message(chat_id, f"⏳ آماده‌سازی دانلود...{FOOTER}")

        # Check cache in DB channel
        if DB_CHANNEL_ID:
            cached_msg_id = await self.cache.get_audio(track_id)
            if cached_msg_id:
                try:
                    await self.bot.forward_message(chat_id, DB_CHANNEL_ID, cached_msg_id)
                    await status_msg.edit(f"✅ آهنگ از دیتابیس دریافت شد.{FOOTER}")
                    return
                except Exception as e:
                    logger.warning(f"Forward failed, re-download: {e}")

        # Fetch track info
        track_data = await self.itunes.get_track(track_id, status_msg)
        if not track_data:
            await status_msg.edit(f"❌ اطلاعات آهنگ یافت نشد.{FOOTER}")
            return
        track = track_data["results"][0]
        title = track["trackName"]
        artist = track["artistName"]
        album = track.get("collectionName", "")
        cover_url = self._high_res_artwork(track.get("artworkUrl100"), 600)

        query = f"{title} {artist}"
        await status_msg.edit(f"🔍 جستجو در یوتیوب موزیک...{FOOTER}")
        video_id = await self.yt.search_track(query)
        if not video_id:
            await status_msg.edit(f"❌ لینک یوتیوب پیدا نشد.{FOOTER}")
            return
        video_url = f"https://music.youtube.com/watch?v={video_id}"

        await status_msg.edit(f"⏳ دانلود با ۸ روش ضدتحریم...{FOOTER}")
        try:
            mp3_path = await asyncio.get_event_loop().run_in_executor(None, download_audio, video_url)
            if mp3_path is None:
                await status_msg.edit(f"❌ همه روش‌ها ناموفق بودند.{FOOTER}")
                return

            # Fetch cover
            cover_bytes = None
            if cover_url:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(cover_url) as resp:
                        if resp.status == 200:
                            cover_bytes = await resp.read()

            # Tag MP3
            await asyncio.get_event_loop().run_in_executor(None, tag_mp3, mp3_path, title, artist, album, cover_bytes)

            file_size = mp3_path.stat().st_size / (1024 * 1024)
            caption = f"🎵 {title}\n🎤 {artist}\n📀 {album}\n🔊 MP3 320kbps | {file_size:.1f} MB{FOOTER}"

            # Upload to DB channel first (if enabled)
            if DB_CHANNEL_ID:
                try:
                    with open(mp3_path, 'rb') as f:
                        db_msg = await self.bot.send_audio(int(DB_CHANNEL_ID), audio=f, caption=caption)
                    await self.cache.set_audio(track_id, db_msg.message_id)
                    # Forward to user
                    await self.bot.forward_message(chat_id, DB_CHANNEL_ID, db_msg.message_id)
                    await status_msg.edit(f"✅ آهنگ با موفقیت ارسال شد (ذخیره در دیتابیس).{FOOTER}")
                except Exception as e:
                    logger.error(f"DB channel upload failed: {e}")
                    # Fallback: send directly
                    with open(mp3_path, 'rb') as f:
                        await self.bot.send_audio(chat_id, audio=f, caption=caption)
                    await status_msg.edit(f"✅ آهنگ ارسال شد (دیتابیس در دسترس نیست).{FOOTER}")
            else:
                with open(mp3_path, 'rb') as f:
                    await self.bot.send_audio(chat_id, audio=f, caption=caption)
                await status_msg.edit(f"✅ دانلود و ارسال شد.{FOOTER}")

            mp3_path.unlink(missing_ok=True)

        except Exception as e:
            logger.exception("Download error")
            await status_msg.edit(f"❌ خطا: {e}{FOOTER}")

    async def _send_preview(self, chat_id: int, track_id: int):
        status_msg = await self.bot.send_message(chat_id, f"⏳ دریافت پیش‌نمایش...{FOOTER}")
        track_data = await self.itunes.get_track(track_id)
        if not track_data:
            await status_msg.edit(f"❌ اطلاعات آهنگ یافت نشد.{FOOTER}")
            return
        preview_url = track_data["results"][0].get("previewUrl")
        if not preview_url:
            await status_msg.edit(f"❌ پیش‌نمایشی موجود نیست.{FOOTER}")
            return
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(preview_url) as resp:
                    if resp.status == 200:
                        audio_bytes = await resp.read()
                        await self.bot.send_audio(chat_id, audio=audio_bytes, caption=f"🎧 پیش‌نمایش{FOOTER}")
                        await status_msg.delete()
                    else:
                        await status_msg.edit(f"❌ خطا در دریافت پیش‌نمایش.{FOOTER}")
        except Exception as e:
            logger.error(f"Preview error: {e}")
            await status_msg.edit(f"❌ خطا در ارسال پیش‌نمایش.{FOOTER}")

    # ---------- Utilities ----------
    @staticmethod
    def _format_duration(millis: int) -> str:
        if not millis:
            return "نامشخص"
        m = millis // 60000
        s = (millis % 60000) // 1000
        return f"{m}:{s:02d}"

    @staticmethod
    def _high_res_artwork(url: str, size: int = 600) -> str:
        return url.replace("100x100bb", f"{size}x{size}bb") if url else ""

# ---------- Main Entry Point ----------
if __name__ == "__main__":
    BOT_NAME = "ابرآوا"
    cache = CacheManager()
    itunes = iTunesClient(cache)
    yt = YouTubeHelper()
    bot_app = AbraavaBot(BOT_TOKEN, cache, itunes, yt)
    logger.info(f"🎵 {BOT_NAME} Music Bot starting...")
    try:
        bot_app.start()
    finally:
        asyncio.get_event_loop().run_until_complete(itunes.close())
