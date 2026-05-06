import os
import re
import asyncio
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

from balethon import Client
from balethon.conditions import private
from balethon.objects import InlineKeyboard, CallbackQuery
import yt_dlp

# ==================== Configuration ====================
BOT_TOKEN = "1011430416:5JY8CU9nGwYtVz0ahfDEIkJyCkVTUCAhLXQ"
DOWNLOAD_PATH = "./downloads"
ITEMS_PER_PAGE = 5

os.makedirs(DOWNLOAD_PATH, exist_ok=True)


# ==================== Data Models ====================
class SearchType(Enum):
    ARTIST = "artist"
    ALBUM = "album"
    TRACK = "track"


@dataclass
class SearchResult:
    title: str
    url: str
    duration: int
    uploader: str
    thumbnail: Optional[str] = None


# ==================== YouTube Music Search ====================
class YouTubeMusicSearcher:
    def __init__(self):
        self.ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}

    def search_tracks(self, query: str, limit: int = 20) -> List[SearchResult]:
        results = []
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                search_query = f"ytsearch{limit}:{query}"
                info = ydl.extract_info(search_query, download=False)
                if 'entries' in info:
                    for entry in info['entries'][:limit]:
                        if entry:
                            results.append(SearchResult(
                                title=entry.get('title', 'Unknown'),
                                url=f"https://youtube.com/watch?v={entry['id']}",
                                duration=entry.get('duration', 0),
                                uploader=entry.get('channel', entry.get('uploader', 'Unknown')),
                                thumbnail=entry.get('thumbnail')
                            ))
        except Exception as e:
            print(f"Search error: {e}")
        return results

    async def download_audio(self, url: str, title: str) -> Optional[str]:
        safe_title = re.sub(r'[^\w\-_\. ]', '_', title)
        output_template = os.path.join(DOWNLOAD_PATH, f"{safe_title}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_template,
            'quiet': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                mp3_filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                if os.path.exists(mp3_filename):
                    return mp3_filename
        except Exception as e:
            print(f"Download error: {e}")
        return None


# ==================== Pagination Manager ====================
class PaginationManager:
    def __init__(self):
        self.user_sessions: Dict[str, Dict] = {}

    def get_session(self, user_id: str) -> Dict:
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {'items': [], 'page': 0, 'last_message_id': None}
        return self.user_sessions[user_id]

    def set_items(self, session: Dict, items: List):
        session['items'] = items
        session['page'] = 0

    def get_current_items(self, session: Dict) -> List:
        start = session['page'] * ITEMS_PER_PAGE
        return session['items'][start:start + ITEMS_PER_PAGE]

    def next_page(self, session: Dict) -> bool:
        if (session['page'] + 1) * ITEMS_PER_PAGE < len(session['items']):
            session['page'] += 1
            return True
        return False

    def prev_page(self, session: Dict) -> bool:
        if session['page'] > 0:
            session['page'] -= 1
            return True
        return False


# ==================== Balethon Bot ====================
bot = Client(BOT_TOKEN)
searcher = YouTubeMusicSearcher()
pagination = PaginationManager()


@bot.on_command(private)
async def start(*, message):
    await message.reply(
        "🎵 **Welcome to YouTube Music Bot!**\n\n"
        "**Commands:**\n"
        "/artist [name] - Search for artists\n"
        "/album [name] - Search for albums\n"
        "/track [name] - Search for tracks\n"
        "/help - Show help"
    )


@bot.on_command(private, name="help")
async def help_command(*, message):
    await message.reply(
        "📖 **How to Use:**\n"
        "/artist [artist name]\n"
        "/album [album name]\n"
        "/track [song name]\n\n"
        "Example:\n`/track Shape of You`"
    )


@bot.on_message(private)
async def message_handler(*, message):
    print("f")
    query = message.text.replace("/track", "").strip()
    if not query:
        await message.reply("❌ Please provide a track name.\nExample: `/track Shape of You`")
        return

    status = await message.reply(f"🔍 Searching for: **{query}**...")
    tracks = searcher.search_tracks(query)
    await status.delete()

    if not tracks:
        await message.reply(f"❌ No tracks found for '{query}'")
        return

    session = pagination.get_session(str(message.author.id))
    pagination.set_items(session, tracks)
    await send_track_page(message, session)


async def send_track_page(message, session):
    items = pagination.get_current_items(session)
    total_pages = (len(session['items']) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    current_page = session['page'] + 1

    text = f"🎵 **Track Search Results**\nPage {current_page}/{total_pages}\n\n"
    for idx, track in enumerate(items, 1):
        minutes, seconds = divmod(track.duration, 60)
        text += f"{idx}. **{track.title}**\n   👤 {track.uploader}\n   ⏱️ {minutes}:{seconds:02d}\n\n"

    # Create inline keyboard with buttons
    keyboard = InlineKeyboard()
    nav_buttons = []
    if pagination.prev_page(session):
        nav_buttons.append(("◀️ Previous", "prev_track"))
    if pagination.next_page(session):
        nav_buttons.append(("Next ▶️", "next_track"))

    if nav_buttons:
        keyboard.add_row(*nav_buttons)

    # Add numbered selection buttons
    for idx in range(len(items)):
        keyboard.add_row((f"🎵 {idx + 1}", f"select_{idx}"))

    # Send or edit message
    if session.get('last_message_id'):
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=session['last_message_id'],
            text=text,
            reply_markup=keyboard
        )
    else:
        sent = await message.reply(text, reply_markup=keyboard)
        session['last_message_id'] = sent.id


@bot.on_callback_query()
async def handle_callback(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    session = pagination.get_session(user_id)
    action = callback.data

    if action == "next_track":
        if pagination.next_page(session):
            await send_track_page(callback.message, session)
        await callback.answer()
    elif action == "prev_track":
        if pagination.prev_page(session):
            await send_track_page(callback.message, session)
        await callback.answer()
    elif action.startswith("select_"):
        index = int(action.split("_")[1])
        items = pagination.get_current_items(session)
        if 0 <= index < len(items):
            track = items[index]
            await callback.answer(f"Downloading: {track.title[:30]}...")

            status = await callback.message.reply(f"⬇️ Downloading **{track.title}**...")
            audio_file = await searcher.download_audio(track.url, track.title)
            await status.delete()

            if audio_file:
                with open(audio_file, 'rb') as f:
                    await bot.send_audio(
                        chat_id=callback.message.chat.id,
                        audio=f.read(),
                        title=track.title,
                        performer=track.uploader,
                        duration=track.duration
                    )
                os.remove(audio_file)
            else:
                await callback.message.reply(f"❌ Failed to download **{track.title}**")
    else:
        await callback.answer()


if __name__ == "__main__":
    print("🤖 Bot is starting...")
    bot.run()
