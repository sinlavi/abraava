import logging
from pathlib import Path

from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC

logger = logging.getLogger("ABRAAVA:TAGEDITOR")


def tag_mp3(file_path: Path, title: str, artist: str, album: str, cover_bytes: bytes):
    """Add ID3 metadata to the downloaded MP3 file."""
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
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=cover_bytes
            ))
        audio.save(file_path, v2_version=3)
        logger.info(f"Metadata updated successfully for {title}")
    except Exception as e:
        logger.error(f"Failed to tag MP3 {file_path}: {e}")
