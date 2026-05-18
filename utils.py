import logging
from pathlib import Path
from typing import Optional

from balethon import Client
from balethon.objects import InlineKeyboard, Message, InlineKeyboardButton
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TCOM, TCON, TDRC, TPOS, TRCK, COMM, TLEN, TXXX, TCOP, TPUB
from ytmusicapi import ytmusic

from config import FOOTER

logger = logging.getLogger("ABRAAVA:TAGEDITOR")


def tag_mp3(file_path: Path, track_data: dict, cover_bytes: bytes = None):
    """Add comprehensive ID3 metadata to the downloaded MP3 file."""
    try:
        audio = ID3(file_path)

        # Basic track information
        if track_data.get('trackName'):
            audio.add(TIT2(encoding=3, text=track_data['trackName']))

        if track_data.get('artistName'):
            audio.add(TPE1(encoding=3, text=track_data['artistName']))

        if track_data.get('collectionName'):
            audio.add(TALB(encoding=3, text=track_data['collectionName']))

        # Additional metadata
        if track_data.get('trackNumber'):
            audio.add(TRCK(encoding=3, text=str(track_data['trackNumber'])))

        if track_data.get('discNumber'):
            audio.add(TPOS(encoding=3, text=str(track_data['discNumber'])))

        # Release year
        if track_data.get('releaseDate'):
            year = track_data['releaseDate'].split('-')[0]
            audio.add(TDRC(encoding=3, text=year))

        # Genre
        if track_data.get('primaryGenreName'):
            audio.add(TCON(encoding=3, text=track_data['primaryGenreName']))

        # Composer (if available from artist)
        if track_data.get('artistName'):
            audio.add(TCOM(encoding=3, text=track_data['artistName']))

        # Duration in milliseconds
        if track_data.get('trackTimeMillis'):
            duration_sec = track_data['trackTimeMillis'] // 1000
            minutes = duration_sec // 60
            seconds = duration_sec % 60
            audio.add(TLEN(encoding=3, text=str(track_data['trackTimeMillis'])))

            # Optional: Add as comment
            audio.add(COMM(encoding=3, lang='eng', desc='Duration',
                           text=f"{minutes}:{seconds:02d}"))

        # Add iTunes ID information as user text frames
        if track_data.get('trackId'):
            audio.add(TXXX(encoding=3, desc='iTunesTrackId', text=str(track_data['trackId'])))

        if track_data.get('artistId'):
            audio.add(TXXX(encoding=3, desc='iTunesArtistId', text=str(track_data['artistId'])))

        if track_data.get('collectionId'):
            audio.add(TXXX(encoding=3, desc='iTunesCollectionId', text=str(track_data['collectionId'])))

        # Explicit content flag
        if track_data.get('trackExplicitness') == 'explicit':
            audio.add(TXXX(encoding=3, desc='Explicit', text='1'))

        # Copyright information
        if track_data.get('copyright'):
            audio.add(TCOP(encoding=3, text=track_data['copyright']))

        # Label/Publisher
        if track_data.get('recordLabel'):
            audio.add(TPUB(encoding=3, text=track_data['recordLabel']))

        # Add cover art
        if cover_bytes:
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,  # Cover (front)
                desc='Cover',
                data=cover_bytes
            ))

        # Save with ID3 v2.3 for better compatibility
        audio.save(file_path, v2_version=3)
        logger.info(f"Metadata updated successfully for {track_data.get('trackName', 'Unknown')}")

    except Exception as e:
        logger.error(f"Failed to tag MP3 {file_path}: {e}")


def create_retry_button(callback_data: str, button_text: str = "🔄 تلاش مجدد") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=button_text, callback_data=f"retry:{callback_data}")


def create_close_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="❌ بستن", callback_data="close")


async def send_error_with_retry(bot: Client, chat_id: int, error_text: str, retry_callback: str,
                                original_message: Optional[Message] = None):
    markup = [
        [create_retry_button(retry_callback)],
    ]

    if original_message:
        try:
            await send_message(bot, chat_id, f"❌ *خطا:* {error_text}", reply_markup=markup)
        except Exception as e:
            await send_message(chat_id, f"❌ *خطا:* {error_text}", reply_markup=markup)
    else:
        await send_message(bot, chat_id, f"❌ *خطا:* {error_text}", reply_markup=markup)
    if original_message:
        await original_message.delete()


async def update_status_with_close(status_msg: Message, text: str, reply_markup=[], no=False):
    try:
        await edit_message(status_msg, text, reply_markup=reply_markup, no=no)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")


async def send_message(bot: Client, chat_id: int, text: str, reply_markup=None):
    if reply_markup is None:
        reply_markup = []
    reply_markup.append([create_close_button()])
    message = await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=InlineKeyboard(*reply_markup))
    return message


async def send_photo(bot: Client, chat_id: int, photo, caption: str, reply_markup=None):
    if reply_markup is None:
        reply_markup = []
    reply_markup.append([create_close_button()])
    logger.info(photo)
    message = await bot.send_photo(chat_id, caption=f"{caption}{FOOTER}", photo=photo,
                                   reply_markup=InlineKeyboard(*reply_markup))
    return message


async def send_voice(bot: Client, chat_id: int, voice, caption: str, reply_markup=None):
    if reply_markup is None:
        reply_markup = []
    reply_markup.append([create_close_button()])
    message = await bot.send_voice(chat_id, caption=f"{caption}{FOOTER}", voice=voice,
                                   reply_markup=InlineKeyboard(*reply_markup))
    return message


async def send_audio(bot: Client, chat_id: int, audio, caption: str, reply_markup=None):
    if reply_markup is None:
        reply_markup = []
    reply_markup.append([create_close_button()])
    message = await bot.send_audio(chat_id, caption=f"{caption}{FOOTER}", audio=audio,
                                   reply_markup=InlineKeyboard(*reply_markup))
    return message


async def edit_message(message: Message, text: str, reply_markup=None, no=False):
    if reply_markup is None:
        reply_markup = []
    if no == False:
        reply_markup.append([create_close_button()])
    message = await message.edit(text=f"{text}{FOOTER}", reply_markup=InlineKeyboard(*reply_markup))
    return message


async def reply_message(message: Message, text: str, reply_markup=None):
    if reply_markup is None:
        reply_markup = []
    reply_markup.append([create_close_button()])
    message = await message.reply(text=f"{text}{FOOTER}", reply_markup=InlineKeyboard(*reply_markup))
    return message
