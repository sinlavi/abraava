import hashlib
import time
from core.config import DEEP_LINK_BASE
from typing import Any, Union, Optional

def format_duration(milliseconds: Union[int, str, None]) -> str:
    """Convert milliseconds to MM:SS format"""
    try:
        if isinstance(milliseconds, str):
            ms = int(milliseconds) if milliseconds.isdigit() else 0
        elif milliseconds is None:
            ms = 0
        else:
            ms = int(milliseconds)

        seconds = ms // 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}:{seconds:02d}"
    except (ValueError, TypeError):
        return "0:00"

def get_high_res_artwork(artwork_url: Optional[str], size: int = 400) -> Optional[str]:
    """Get high resolution artwork by replacing size in URL"""
    if not artwork_url: return None
    try:
        url = str(artwork_url)
        if "{w}" in url: url = url.replace("{w}", str(size))
        if "{h}" in url: url = url.replace("{h}", str(size))
        if "100x100" in url: url = url.replace("100x100", f"{size}x{size}")
        return url
    except Exception: return artwork_url

def generate_search_hash(search_type: str, search_term: str) -> str:
    """Generate a unique hash for search caching"""
    combined = f"{search_type}:{search_term}".lower()
    return hashlib.md5(combined.encode()).hexdigest()

def generate_deep_link(type_: str, item_id: Any) -> str:
    """Generate a deep link for a bot entity"""
    return f"{DEEP_LINK_BASE}{type_}_{item_id}"
