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
