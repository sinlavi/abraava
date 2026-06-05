from typing import Optional, Tuple

async def parse_search_query(text: str) -> Optional[Tuple[str, str]]:
    text = text.strip()
    if not text:
        return None

    if text.startswith("/search"):
        text = text[7:].strip()
        return "track", text
    elif text.startswith("/album"):
        text = text[6:].strip()
        return "album", text
    elif text.startswith("/track"):
        text = text[6:].strip()
        return "track", text
    elif text.startswith("/artist"):
        text = text[7:].strip()
        return "artist", text
    elif text.startswith("/quick"):
        text = text[6:].strip()
        return "quick", text
    else:
        return "track", text
