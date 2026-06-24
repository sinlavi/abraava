import hashlib
import time
import re
import os
import sys
from anyascii import anyascii
from core.config import DEEP_LINK_BASE
from typing import Any

def has_persian(text: str) -> bool:
    """Check if text contains Persian characters"""
    if not text: return False
    return bool(re.search(r'[\u0600-\u06FF]', text))

_g2p_converter = None

def to_fingilish(text: str) -> str:
    """Convert Persian text to Fingilish (ASCII)"""
    global _g2p_converter
    if not text: return text

    try:
        if _g2p_converter is None:
            from PersianG2p.G2P import Persian_g2p_converter
            _g2p_converter = Persian_g2p_converter()

        # PersianG2p transliterate might return phonemes like 'čāvoši'
        phonetic = _g2p_converter.transliterate(text)
        # Use anyascii to normalize phonetic symbols to plain ASCII
        return anyascii(phonetic).strip().replace('  ', ' ')
    except Exception:
        # Fallback to anyascii if PersianG2p fails
        return anyascii(text)

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
