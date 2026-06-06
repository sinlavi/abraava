from typing import Optional, Tuple
import re

async def parse_search_query(text: str) -> Optional[Tuple[str, str]]:
    text = text.strip()
    if not text: return None

    # iTunes/Apple Music link parsing
    # Track/Album
    itunes_match = re.search(r'music\.apple\.com/\w+/album/[^/]+/(\d+)(\?i=(\d+))?', text)
    if itunes_match:
        track_id = itunes_match.group(3)
        album_id = itunes_match.group(1)
        if track_id: return "itunes_track", track_id
        return "itunes_album", album_id

    # Artist
    apple_artist_match = re.search(r'music\.apple\.com/\w+/artist/[^/]+/(\d+)', text)
    if apple_artist_match:
        return "itunes_artist", apple_artist_match.group(1)

    # Spotify / Deezer links
    if "open.spotify.com" in text or "deezer.com" in text:
        return "music_link", text

    # YouTube / SoundCloud direct link detection
    if "youtube.com" in text or "youtu.be" in text or "soundcloud.com" in text:
        return "direct_link", text

    if text.startswith("/search"): return "track", text[7:].strip() or None
    elif text.startswith("/album"): return "album", text[6:].strip() or None
    elif text.startswith("/track"): return "track", text[6:].strip() or None
    elif text.startswith("/artist"): return "artist", text[7:].strip() or None
    elif text.startswith("/quick"): return "quick", text[6:].strip() or None

    return "track", text
