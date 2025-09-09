import os
import time
import asyncio
import requests
import telebot
from uuid import uuid4
from yt_dlp import YoutubeDL
from cachetools import TTLCache
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Initialize bot
bot = telebot.TeleBot("8233533503:AAGXFDukqI8taXzl7mtrpdsbVTzuog1QE0c")

# Initialize caches with TTL (Time To Live)
search_cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL
download_links_cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL

def search_soundcloud(query):
    """Search for tracks on SoundCloud"""
    with YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
        try:
            results = ydl.extract_info(f"scsearch5:{query}", download=False)
            return results.get("entries", [])[:5]  # Limit to 5 results
        except Exception as e:
            print(f"SoundCloud search error: {e}")
            return []

def search_itunes(query):
    """Search for tracks on iTunes"""
    try:
        res = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "music", "limit": 5},
            timeout=10
        )
        return res.json().get("results", [])
    except Exception as e:
        print(f"iTunes search error: {e}")
        return []

def fetch_songlink(url):
    """Fetch song links from song.link API"""
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": url},
            timeout=15
        )
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"Song.link API error: {e}")
        return None

def extract_itunes_data(songlink_data):
    """Extract iTunes metadata from song.link response"""
    platforms = songlink_data.get("linksByPlatform", {})
    itunes = platforms.get("itunes", {})
    entity_id = itunes.get("entityUniqueId")
    return songlink_data.get("entitiesByUniqueId", {}).get(entity_id, {})

def get_priority_download_url(songlink_data):
    """Get the best available download URL"""
    platforms = songlink_data.get("linksByPlatform", {})
    return (
        platforms.get("soundcloud", {}).get("url") or
        platforms.get("youtube", {}).get("url") or
        platforms.get("youtubeMusic", {}).get("url")
    )

def format_song_info(metadata):
    """Format song metadata for display"""
    return (
        f"🎵 *{metadata.get('trackName', 'Unknown Title')}*\n"
        f"👤 *Artist:* {metadata.get('artistName', 'Unknown Artist')}\n"
        f"💿 *Album:* {metadata.get('collectionName', 'Unknown Album')}\n"
        f"📅 *Released:* {metadata.get('releaseDate', 'Unknown')[:10]}\n"
        f"🎶 *Genre:* {metadata.get('primaryGenreName', 'Unknown')}"
    )

def cleanup_file(file_path):
    """Safely remove a file"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")

def download_and_send_audio(chat_id, url, message_id=None):
    """Download audio and send to Telegram"""
    filename = f"{uuid4()}.mp3"
    status_message = bot.send_message(chat_id, "⏳ Downloading file...")
    
    last_update = time.time()
    update_interval = 2  # Update every 2 seconds

    def progress_callback(d):
        nonlocal last_update
        if d['status'] == 'downloading':
            current_time = time.time()
            if current_time - last_update >= update_interval:
                percent = d.get('_percent_str', 'N/A').strip()
                speed = d.get('_speed_str', 'N/A').strip()
                eta = d.get('_eta_str', 'N/A').strip()
                
                progress_text = (
                    f"⬇️ Downloading...\n"
                    f"📊 Progress: {percent}\n"
                    f"🚀 Speed: {speed}\n"
                    f"⏱️ ETA: {eta}"
                )
                
                try:
                    bot.edit_message_text(
                        progress_text, 
                        chat_id, 
                        status_message.message_id
                    )
                except:
                    pass  # Ignore edit errors
                
                last_update = current_time

    ydl_options = {
        "format": "bestaudio/best",
        "outtmpl": filename,
        "quiet": True,
        "noplaylist": True,
        "progress_hooks": [progress_callback],
        "postprocessors": [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with YoutubeDL(ydl_options) as ydl:
            ydl.download([url])
        
        # Check if file was created
        if not os.path.exists(filename):
            raise Exception("Downloaded file not found")

        # Send audio file
        with open(filename, 'rb') as audio_file:
            bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                caption="✅ Download completed!",
                reply_to_message_id=message_id
            )
        
        bot.delete_message(chat_id, status_message.message_id)

    except Exception as e:
        error_msg = f"❌ Download error: {str(e)}"
        bot.edit_message_text(
            error_msg, 
            chat_id, 
            status_message.message_id
        )
        print(f"Download error: {e}")
    
    finally:
        cleanup_file(filename)

def send_song_details(chat_id, metadata, songlink_data, message_id=None):
    """Send formatted song information with download options"""
    caption = format_song_info(metadata)
    artwork_url = metadata.get("artworkUrl100", "").replace("100x100", "600x600")
    download_id = str(uuid4())
    
    # Store in cache
    download_links_cache[download_id] = songlink_data

    # Create inline keyboard
    keyboard = InlineKeyboardMarkup()
    
    # Add preview button if available
    preview_url = metadata.get("previewUrl")
    if preview_url:
        keyboard.add(InlineKeyboardButton("🎧 Preview", callback_data=f"preview_{preview_url}"))
    
    # Add download button
    download_url = get_priority_download_url(songlink_data)
    if download_url:
        keyboard.add(InlineKeyboardButton("⬇️ Download", callback_data=f"download_{download_id}"))
    
    # Add search again button
    keyboard.add(InlineKeyboardButton("🔍 Search Again", callback_data="search_again"))

    try:
        bot.send_photo(
            chat_id=chat_id,
            photo=artwork_url,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
            reply_to_message_id=message_id
        )
    except Exception as e:
        # Fallback to text if photo fails
        bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
            reply_to_message_id=message_id
        )

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Handle incoming messages"""
    chat_id = message.chat.id
    text = message.text.strip()
    message_id = message.message_id

    if not text:
        bot.send_message(chat_id, "🎵 Please send me a song name to search!")
        return

    # Show typing action
    bot.send_chat_action(chat_id, "typing")

    # Search both platforms
    soundcloud_results = search_soundcloud(text)
    itunes_results = search_itunes(text)
    all_results = soundcloud_results + itunes_results

    if not all_results:
        bot.send_message(chat_id, "❌ No results found. Try a different search term.")
        return

    # Create search cache entry
    search_id = str(uuid4())
    search_cache[search_id] = {
        "results": all_results[:8],  # Limit to 8 results
        "timestamp": time.time(),
        "query": text
    }

    # Create inline keyboard with results
    keyboard = InlineKeyboardMarkup()
    for idx, item in enumerate(all_results[:8], 1):
        title = item.get("title") or item.get("trackName") or "Unknown Title"
        artist = item.get("uploader") or item.get("artistName") or "Unknown Artist"
        
        keyboard.add(InlineKeyboardButton(
            f"{idx}. {title[:30]} - {artist[:20]}", 
            callback_data=f"select_{search_id}_{idx-1}"
        ))

    keyboard.add(InlineKeyboardButton("🔍 New Search", callback_data="new_search"))

    bot.send_message(
        chat_id,
        f"🔍 Found {len(all_results)} results for: *{text}*",
        parse_mode="Markdown",
        reply_markup=keyboard,
        reply_to_message_id=message_id
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(callback):
    """Handle inline button callbacks"""
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    data = callback.data

    bot.answer_callback_query(callback.id)  # Acknowledge callback

    if data == "new_search" or data == "search_again":
        bot.send_message(chat_id, "🔍 Send me the name of the song you want to search:")
        return

    elif data.startswith("preview_"):
        preview_url = data[8:]
        bot.send_voice(chat_id, voice=preview_url, reply_to_message_id=message_id)

    elif data.startswith("download_"):
        download_id = data[9:]
        song_data = download_links_cache.get(download_id)
        
        if not song_data:
            bot.send_message(chat_id, "❌ Download link expired. Please search again.")
            return

        download_url = get_priority_download_url(song_data)
        if download_url:
            # Run download in a separate thread to avoid blocking
            thread = Thread(target=download_and_send_audio, args=(chat_id, download_url, message_id))
            thread.start()
        else:
            bot.send_message(chat_id, "❌ No download available for this track.")

    elif data.startswith("select_"):
        parts = data.split("_")
        if len(parts) != 3:
            return

        search_id = parts[1]
        result_index = int(parts[2])
        
        search_data = search_cache.get(search_id)
        if not search_data or time.time() - search_data["timestamp"] > 3600:
            bot.send_message(chat_id, "❌ Search results expired. Please search again.")
            return

        results = search_data["results"]
        if result_index >= len(results):
            bot.send_message(chat_id, "❌ Invalid selection.")
            return

        selected_item = results[result_index]
        item_url = selected_item.get("webpage_url") or selected_item.get("trackViewUrl")
        
        if not item_url:
            bot.send_message(chat_id, "❌ No URL available for this track.")
            return

        bot.send_chat_action(chat_id, "typing")
        
        # Fetch song.link data
        songlink_data = fetch_songlink(item_url)
        if not songlink_data:
            bot.send_message(chat_id, "❌ Could not fetch track information.")
            return

        # Try to get iTunes metadata
        itunes_meta = extract_itunes_data(songlink_data)
        if itunes_meta:
            send_song_details(chat_id, itunes_meta, songlink_data, message_id)
        else:
            # Fallback to direct download
            download_url = get_priority_download_url(songlink_data)
            if download_url:
                # Run download in a separate thread to avoid blocking
                thread = Thread(target=download_and_send_audio, args=(chat_id, download_url, message_id))
                thread.start()
            else:
                bot.send_message(chat_id, "❌ No download available for this track.")

if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()