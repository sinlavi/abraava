from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

class DownloadQuality(Enum):
    HIGH = "320"
    MEDIUM = "192"
    LOW = "128"
    ASK = "ask"

QUALITY_MULTIPLIER = {
    "320": 3,
    "192": 2,
    "128": 1
}

SUPPORTED_QUALITIES = ["320", "192", "128"]
DEFAULT_QUALITY = "192"

def estimate_size_mb(duration_ms: int, quality_kbps: str) -> float:
    """Estimate MP3 file size in MB based on duration and quality."""
    try:
        q = int(quality_kbps)
        duration_s = duration_ms / 1000
        # bitrate (kbps) * seconds / 8 = KB
        size_kb = (q * duration_s) / 8
        return size_kb / 1024
    except (ValueError, TypeError):
        return 0.0

def get_best_quality_for_size(duration_ms: int, limit_mb: int = 20) -> Optional[str]:
    """Return the highest supported quality that fits within the size limit."""
    for q in SUPPORTED_QUALITIES:
        if estimate_size_mb(duration_ms, q) <= limit_mb:
            return q
    return None

@dataclass
class UserSettings:
    user_id: int
    quick_mode: bool = False
    download_quality: DownloadQuality = DownloadQuality.MEDIUM
    show_artwork: bool = True
    auto_download: bool = False
    notifications: bool = True

@dataclass
class TrackDownloadStatus:
    name: str
    success: bool = False
    error: Optional[str] = None
    order: int = 0
    start_time: float = 0
    duration: float = 0

@dataclass
class AlbumDownloadInfo:
    status_msg: Any
    tracks: List[TrackDownloadStatus] = field(default_factory=list)
    current_idx: int = 0
    total: int = 0
    cancelled: bool = False
    cancelled_time: float = 0
    collection_name: str = ""
    start_time: float = 0
    cover_bytes: Optional[bytes] = None
