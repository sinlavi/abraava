import json
import re
import urllib.parse
from typing import Any, Tuple, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def extract_url(text: str) -> Optional[str]:
    url_pattern = re.compile(r'(https?://[^\s]+)')
    match = url_pattern.search(text)
    if match:
        url = match.group(0)
        try:
            result = urllib.parse.urlparse(url)
            if all([result.scheme, result.netloc]):
                return url
        except ValueError:
            return False
    return False


def cb_make(prefix: str, payload: str) -> str:
    """Create compact callback_data: prefix|payload"""
    full_data = f"{prefix}|{payload}"
    if len(full_data.encode("utf-8")) > 64:
        max_payload_length = 64 - len(prefix.encode("utf-8")) - 1
        payload = payload.encode("utf-8")[:max_payload_length].decode("utf-8", "ignore")
    return f"{prefix}|{payload}"


def cb_parse(data: str) -> Tuple[str, str]:
    if "|" not in data:
        return data, ""
    return data.split("|", 1)


def safe_json_loads_text(content: str) -> Any:
    return json.loads(content)


def convert_results_to_buttons(results):
    buttons = []
    for result in results:
        buttons.append([InlineKeyboardButton("🎵 " + result['title'] + " - " + result["artist"],
                                             callback_data=cb_make("info", result['url']))])
    return buttons
