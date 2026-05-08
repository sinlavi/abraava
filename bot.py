# pip install balethon yt-dlp

import asyncio
from urllib.parse import quote_plus

from yt_dlp import YoutubeDL
from balethon import Client
from balethon.objects import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BALE_BOT_TOKEN")

bot = Client(TOKEN)


# ---------------- SEARCH ----------------

def search_ytmusic(query, limit=5):

    search_url = (
        f"https://music.youtube.com/search?q="
        f"{quote_plus(query)}#songs"
    )

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": limit,
    }

    results = []

    with YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(search_url, download=False)

        for entry in data.get("entries", [])[:limit]:

            if not entry:
                continue

            video_id = entry.get("id")
            title = entry.get("title", "Unknown")
            artist = entry.get("uploader", "Unknown")

            results.append({
                "id": video_id,
                "title": title,
                "artist": artist,
            })

    return results


# ---------------- COMMANDS ----------------

@bot.on_message()
async def on_message(message):

    text = (message.text or "").strip()

    if text == "/start":

        await message.reply(
            "🎵 YouTube Music Search Bot\n\n"
            "Usage:\n"
            "/search song name"
        )
        return

    if text.startswith("/search "):

        query = text.split(" ", 1)[1].strip()

        await message.reply(
            "🔎 Searching YouTube Music..."
        )

        try:
            results = await asyncio.to_thread(
                search_ytmusic,
                query,
                5
            )

        except Exception as e:
            await message.reply(f"Error:\n{e}")
            return

        if not results:
            await message.reply("Nothing found.")
            return

        for item in results:

            text_msg = (
                f"🎵 {item['title']}\n"
                f"👤 {item['artist']}"
            )

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎧 Open",
                        url=(
                            "https://music.youtube.com/"
                            f"watch?v={item['id']}"
                        )
                    ),

                    InlineKeyboardButton(
                        "⬇️ Download",
                        callback_data=(
                            f"dl:{item['id']}"
                        )
                    )
                ]
            ])

            await bot.send_message(
                chat_id=message.chat.id,
                text=text_msg,
                reply_markup=keyboard
            )


# ---------------- CALLBACK ----------------

@bot.on_callback_query()
async def on_callback(callback):

    data = callback.data or ""

    if data.startswith("dl:"):

        video_id = data.replace("dl:", "")

        # اینجا عمداً دانلود واقعی انجام نمی‌شود.
        # فقط نمونه send_audio گذاشته شده.

        await callback.answer(
            "Download feature disabled."
        )

        # نمونه ارسال فایل قانونی/لوکال:
        #
        # await bot.send_audio(
        #     chat_id=callback.message.chat.id,
        #     audio="music.mp3",
        #     title="Sample Audio"
        # )


bot.run()
