import json
import urllib.parse
from typing import Any, Tuple

def is_valid_url(url_string: str) -> bool:
    try:
        result = urllib.parse.urlparse(url_string)
        return all([result.scheme, result.netloc])
    except ValueError:
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
