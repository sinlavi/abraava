import os
from pathlib import Path
from typing import Optional
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TCOM, TCON, TDRC, TPOS, TRCK, COMM, TLEN, TXXX, TCOP, TPUB, USLT
from core.logger import logger

class TaggingService:
    @staticmethod
    def tag_mp3(file_path: Path, track_data: dict, cover_bytes: Optional[bytes] = None, lyrics: Optional[str] = None):
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
                audio.add(TLEN(encoding=3, text=str(track_data['trackTimeMillis'])))

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

            # Add hashtags to comment
            hashtags = []
            if track_data.get('primaryGenreName'):
                hashtags.append(f"#{track_data['primaryGenreName'].replace(' ', '_')}")
            if track_data.get('artistName'):
                from crawlers.utils import format_artist_hashtag
                hashtags.append(format_artist_hashtag(track_data['artistName']))

            if hashtags:
                comment_text = " ".join(hashtags)
                audio.add(COMM(encoding=3, lang='eng', desc='desc', text=comment_text))

            # Add cover art
            if cover_bytes:
                audio.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,  # Cover (front)
                    desc='Cover',
                    data=cover_bytes
                ))

            # Add lyrics
            if lyrics:
                audio.add(USLT(encoding=3, lang='eng', desc='Lyrics', text=lyrics))

            # Save with ID3 v2.3 for better compatibility
            audio.save(file_path, v2_version=3)
            logger.info(f"Metadata updated successfully for {track_data.get('trackName', 'Unknown')}")

        except Exception as e:
            logger.error(f"Failed to tag MP3 {file_path}: {e}")
