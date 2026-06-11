import pytest
from utils.helpers import format_duration, get_high_res_artwork, generate_deep_link
from core.config import DEEP_LINK_BASE

def test_format_duration():
    assert format_duration(60000) == "1:00"
    assert format_duration(125000) == "2:05"
    assert format_duration(0) == "0:00"
    assert format_duration(None) == "0:00"
    assert format_duration("not a number") == "0:00"

def test_get_high_res_artwork():
    url = "https://example.com/100x100bb.jpg"
    assert get_high_res_artwork(url, 500) == "https://example.com/500x500bb.jpg"
    assert get_high_res_artwork(None) is None

    template_url = "https://example.com/{w}x{h}bb.jpg"
    assert get_high_res_artwork(template_url, 600) == "https://example.com/600x600bb.jpg"

def test_generate_deep_link():
    assert generate_deep_link("track", 123) == f"{DEEP_LINK_BASE}track_123"
    assert generate_deep_link("artist", "abc") == f"{DEEP_LINK_BASE}artist_abc"
