import time
from typing import Dict, List, Union
from collections import defaultdict
from models.schemas import QUALITY_MULTIPLIER

class RateLimiter:
    def __init__(self, max_requests: int = 30, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.users: Dict[int, List[float]] = {}
        self.global_count = 0
        self.global_reset = time.time()
        self.max_global = 30

    async def check_user(self, user_id: int) -> tuple[bool, int]:
        now = time.time()
        if now - self.global_reset > self.time_window:
            self.global_count = 0
            self.global_reset = now
        if self.global_count >= self.max_global:
            wait_time = int(self.time_window - (now - self.global_reset))
            return False, wait_time

        user_timestamps = self.users.get(user_id, [])
        self.users[user_id] = [ts for ts in user_timestamps if now - ts < self.time_window]

        if len(self.users[user_id]) >= self.max_requests:
            wait_time = int(self.time_window - (now - self.users[user_id][0]))
            return False, wait_time

        self.users[user_id].append(now)
        self.global_count += 1
        return True, 0

    def get_user_remaining(self, user_id: int) -> int:
        now = time.time()
        user_timestamps = self.users.get(user_id, [])
        self.users[user_id] = [ts for ts in user_timestamps if now - ts < self.time_window]
        return max(0, self.max_requests - len(self.users[user_id]))


class DownloadRateLimiter:
    def __init__(self, max_downloads: int = 100, time_window: int = 3600):
        self.max_downloads = max_downloads
        self.time_window = time_window
        self.users: Dict[int, List[float]] = defaultdict(list)

    async def can_download(self, user_id: int, quality: str = "192") -> tuple[bool, int]:
        now = time.time()
        multiplier = QUALITY_MULTIPLIER.get(quality, 1)
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]

        total_used = len(self.users[user_id])
        available_slots = self.max_downloads - total_used

        if available_slots < multiplier:
            oldest = min(self.users[user_id]) if self.users[user_id] else now
            wait_seconds = int(self.time_window - (now - oldest))
            return False, wait_seconds
        return True, 0

    def record_download(self, user_id: int, quality: str = "192"):
        now = time.time()
        multiplier = QUALITY_MULTIPLIER.get(quality, 1)
        for _ in range(multiplier):
            self.users[user_id].append(now)

    def get_remaining(self, user_id: int) -> int:
        now = time.time()
        self.users[user_id] = [ts for ts in self.users[user_id] if now - ts < self.time_window]
        return max(0, self.max_downloads - len(self.users[user_id]))
