import os
import asyncio
from balethon import Client
from balethon.objects import InlineKeyboard
from ytmusicapi import YTMusic
from yt_dlp import YoutubeDL

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BALE_BOT_TOKEN")
COOKIES_PATH = "cookies.txt" 

# Initialize APIs
bot = Client(BOT_TOKEN)
ytm = YTMusic()

# yt-dlp configuration
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'cookiefile': COOKIES_PATH,
    'postprocessors': [
        {
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        },
        {'key': 'FFmpegMetadata'},
        {'key': 'EmbedThumbnail'},
    ],
    'quiet': True,
}

async def download_and_send(chat_id, url):
    """Downloads audio and sends to Bale."""
    status_msg = await bot.send_message(chat_id, "⏳ Processing...")

    with YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)
            # yt-dlp changes extension to .mp3 after post-processing
        file_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
            
        await bot.send_audio(chat_id, file_path, caption=f"✅ {info.get('title')}")
            
        if os.path.exists(file_path):
            os.remove(file_path)
@bot.on_message()
async def handle_messages(message):
    if not message.text:
        return

    if message.text.startswith("/start"):
        await message.reply("🎶 Send a song name or a YouTube link.")
        return

    if "youtube.com" in message.text or "youtu.be" in message.text:
        await download_and_send(message.chat.id, message.text)
        return

    search_query = message.text
    results = ytm.search(search_query)
    print(results)

if __name__ == "__main__":
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    print("Bale Music Bot is running...")
    bot.run()
