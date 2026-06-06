from typing import Optional, Tuple
import re

async def parse_search_query(text: str) -> Optional[Tuple[str, str]]:
    text = text.strip()
    if not text: return None

    # iTunes/Apple Music link parsing
    # Track/Album with name in URL
    itunes_match = re.search(r'music\.apple\.com/\w+/(album|song)/[^/]+/(\d+)(\?i=(\d+))?', text)
    if itunes_match:
        track_id = itunes_match.group(4)
        album_id = itunes_match.group(2)
        if track_id: return "itunes_track", track_id

        type_ = itunes_match.group(1)
        if type_ == "song": return "itunes_track", album_id
        return "itunes_album", album_id

    # Track/Album without name in URL
    itunes_no_name_match = re.search(r'music\.apple\.com/\w+/(album|song)/(\d+)(\?i=(\d+))?', text)
    if itunes_no_name_match:
        track_id = itunes_no_name_match.group(4)
        album_id = itunes_no_name_match.group(2)
        if track_id: return "itunes_track", track_id

        type_ = itunes_no_name_match.group(1)
        if type_ == "song": return "itunes_track", album_id
        return "itunes_album", album_id

    # Artist
    apple_artist_match = re.search(r'music\.apple\.com/\w+/artist/([^/]+/)?(\d+)', text)
    if apple_artist_match:
        return "itunes_artist", apple_artist_match.group(2)

    # Spotify / Deezer links
    music_link_match = re.search(r'(https?://(open\.spotify\.com|www\.deezer\.com|deezer\.com)/[^\s]+)', text)
    if music_link_match:
        return "music_link", music_link_match.group(1)

    # YouTube / SoundCloud direct link detection
    direct_link_match = re.search(r'(https?://(www\.)?(youtube\.com|youtu\.be|soundcloud\.com)/[^\s]+)', text)
    if direct_link_match:
        return "direct_link", direct_link_match.group(1)

    if text.startswith("/search"): return "track", text[7:].strip() or None
    elif text.startswith("/album"): return "album", text[6:].strip() or None
    elif text.startswith("/track"): return "track", text[6:].strip() or None
    elif text.startswith("/artist"): return "artist", text[7:].strip() or None
    elif text.startswith("/quick"): return "quick", text[6:].strip() or None

    return "track", text
