import hashlib
import time
import re
from core.config import DEEP_LINK_BASE, PLATFORM
from typing import Any

def format_markdown(text: str) -> str:
    """Format markdown based on the current platform"""
    if not text:
        return text

    if PLATFORM == "telegram":
        # Convert Bale-style bold (*bold*) to Telegram-style bold (**bold**)
        # This regex looks for text between single asterisks that are not part of other structures
        # We use a simple approach here, assuming standard bot messages
        # Avoid matching triple asterisks or already double asterisks

        # Replace *bold* with **bold**
        # But be careful about escaped asterisks if any
        # A simple regex: (?<!\*)\*([^*]+)\*(?!\*)
        text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'**\1**', text)

    return text

def format_duration(milliseconds):
    """Convert milliseconds to MM:SS format"""
    try:
        if isinstance(milliseconds, str):
            milliseconds = int(milliseconds) if milliseconds.isdigit() else 0
        elif milliseconds is None:
            milliseconds = 0

        seconds = milliseconds // 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}:{seconds:02d}"
    except (ValueError, TypeError):
        return "0:00"

def get_high_res_artwork(artwork_url: str, size: int = 400):
    """Get high resolution artwork by replacing size in URL"""
    if not artwork_url: return None
    try:
        artwork_url = str(artwork_url)
        if "{w}" in artwork_url: artwork_url = artwork_url.replace("{w}", str(size))
        if "{h}" in artwork_url: artwork_url = artwork_url.replace("{h}", str(size))
        if "100x100" in artwork_url: artwork_url = artwork_url.replace("100x100", f"{size}x{size}")
        return artwork_url
    except Exception: return artwork_url

def generate_search_hash(search_type: str, search_term: str) -> str:
    """Generate a unique hash for search caching"""
    combined = f"{search_type}:{search_term}".lower()
    return hashlib.md5(combined.encode()).hexdigest()

def generate_deep_link(type_: str, item_id: Any) -> str:
    """Generate a deep link for a bot entity"""
    return f"{DEEP_LINK_BASE}{type_}_{item_id}"
