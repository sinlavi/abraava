import asyncio
import time
from typing import Dict, Tuple, Optional
from models.schemas import AlbumDownloadInfo, TrackDownloadStatus
from services.api_client import APIClient

class AlbumDownloadTracker:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.active_downloads: Dict[Tuple[int, int], AlbumDownloadInfo] = {}
        self.download_locks: Dict[Tuple[int, int], asyncio.Lock] = {}

    async def acquire_lock(self, user_id: int, collection_id: int) -> bool:
        key = (user_id, collection_id)
        if key not in self.download_locks:
            self.download_locks[key] = asyncio.Lock()
        try:
            await asyncio.wait_for(self.download_locks[key].acquire(), timeout=5.0)
            return True
        except asyncio.TimeoutError:
            return False

    def release_lock(self, user_id: int, collection_id: int):
        key = (user_id, collection_id)
        if key in self.download_locks and self.download_locks[key].locked():
            self.download_locks[key].release()

    def start_download(self, user_id: int, collection_id: int, status_msg, total_tracks: int, collection_name: str):
        key = (user_id, collection_id)
        self.active_downloads[key] = AlbumDownloadInfo(
            status_msg=status_msg,
            total=total_tracks,
            collection_name=collection_name,
            start_time=time.time()
        )

    def add_track(self, user_id: int, collection_id: int, track_name: str, order: int):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key].tracks.append(TrackDownloadStatus(name=track_name, order=order))

    def start_track(self, user_id: int, collection_id: int, track_name: str):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            for track in self.active_downloads[key].tracks:
                if track.name == track_name:
                    track.start_time = time.time()
                    break

    def set_cover_bytes(self, user_id: int, collection_id: int, cover_bytes: bytes):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key].cover_bytes = cover_bytes

    def update_track_result(self, user_id: int, collection_id: int, track_name: str, success: bool, error_msg: str = None):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            tracker = self.active_downloads[key]
            for track in tracker.tracks:
                if track.name == track_name:
                    track.success = success
                    track.error = error_msg
                    track.duration = time.time() - track.start_time if track.start_time > 0 else 0
                    break
            tracker.current_idx += 1

    def get_progress_text(self, user_id: int, collection_id: int) -> str:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return ""
        t = self.active_downloads[key]

        if t.cancelled:
            return f"⏹️ *در حال توقف دانلود آلبوم {t.collection_name}...*"

        completed = sum(1 for tr in t.tracks if tr.success)
        failed = sum(1 for tr in t.tracks if not tr.success and tr.error is not None)
        elapsed = time.time() - t.start_time

        text = f"⬇️ *در حال دانلود آلبوم: {t.collection_name}*\n\n"
        text += f"🎵 *پیشرفت:* {t.current_idx}/{t.total} قطعه\n"
        text += f"✅ *موفق:* {completed}\n"
        text += f"❌ *ناموفق:* {failed}\n\n"

        if t.current_idx < t.total and t.tracks and t.current_idx < len(t.tracks):
            current_track = t.tracks[t.current_idx]
            text += f"🎤 *در حال دانلود:* {current_track.name}\n"
            if current_track.start_time > 0:
                track_elapsed = int(time.time() - current_track.start_time)
                text += f"⏱️ *زمان سپری شده:* {track_elapsed} ثانیه\n\n"
            else:
                text += "\n"

        if t.current_idx > 0 and (completed + failed) > 0:
            avg_time = elapsed / (completed + failed)
            remaining_tracks = t.total - (completed + failed)
            eta = int(avg_time * remaining_tracks)
            if eta > 0:
                minutes, seconds = divmod(eta, 60)
                if minutes > 0:
                    text += f"⏱️ *زمان باقیمانده:* {minutes} دقیقه {seconds} ثانیه"
                else:
                    text += f"⏱️ *زمان باقیمانده:* {seconds} ثانیه"
        return text

    def finish_download(self, user_id: int, collection_id: int, successful_tracks: int = 0, failed_tracks: int = 0):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            t = self.active_downloads[key]
            asyncio.create_task(self.api_client.log_album_download(
                user_id=user_id,
                collection_id=str(collection_id),
                collection_name=t.collection_name,
                artist_name='',
                total_tracks=t.total,
                successful_tracks=successful_tracks,
                failed_tracks=failed_tracks
            ))
            del self.active_downloads[key]
        self.release_lock(user_id, collection_id)

    def is_cancelled(self, user_id: int, collection_id: int) -> bool:
        key = (user_id, collection_id)
        if key not in self.active_downloads:
            return True
        return self.active_downloads[key].cancelled

    def cancel_download(self, user_id: int, collection_id: int):
        key = (user_id, collection_id)
        if key in self.active_downloads:
            self.active_downloads[key].cancelled = True
            self.active_downloads[key].cancelled_time = time.time()
