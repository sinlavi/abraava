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
    
    try:
        with YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp changes extension to .mp3 after post-processing
            file_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
            
            await bot.send_audio(chat_id, file_path, caption=f"✅ {info.get('title')}")
            
            if os.path.exists(file_path):
                os.remove(file_path)
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Error: {str(e)}")
    finally:
        await status_msg.delete()
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
    
    response_text = f"🔍 **Results for:** {search_query}\n\n"
    
    # We will collect our rows here
    keyboard_rows = []
    print(results)
    sections = {
        "song": ("🎵", "Tracks"),
        "album": ("💽", "Albums"),
        "artist": ("👤", "Artists")
    }
    
    for res_type, (emoji, label) in sections.items():
        items = [r for r in results if r['resultType'] == res_type][:3]
        if items:
            response_text += f"{emoji} **{label}**\n"
            for item in items:
                title = item.get('title') or item.get('artist', 'Unknown')
                response_text += f"├ {title}\n"
                
                if res_type == "song":
                    # Create a row with one button
                    button_text = f"📥 Get: {title[:15]}..."
                    callback_data = f"dl_{item['videoId']}"
                    keyboard_rows.append([{button_text: callback_data}])
            response_text += "\n"

    # Pass the list of rows to the InlineKeyboard constructor
    reply_markup = InlineKeyboard(*keyboard_rows)

    await message.reply(response_text, reply_markup=reply_markup)
    
@bot.on_callback_query()
async def handle_callbacks(callback):
    if callback.data.startswith("dl_"):
        video_id = callback.data.split("_")[1]
        url = f"https://www.youtube.com/watch?v={video_id}"
        await callback.answer("Downloading...")
        await download_and_send(callback.message.chat.id, url)

if __name__ == "__main__":
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    print("Bale Music Bot is running...")
    bot.run()
