import aiohttp
from typing import Dict, Any, List, Optional
from core.logger import logger
from core.http_client import HttpClient

class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token

    async def _request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        session = await HttpClient.get_session()
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        try:
            async with session.post(f"{self.base_url}?action={action}", json=data, headers=headers) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {'success': False, 'message': str(e)}

    async def register_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request('register', user_data)

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        return await self._request('get_user', {'user_id': user_id})

    async def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        return await self._request('get_user_settings', {'user_id': user_id})

    async def update_quick_mode(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self._request('update_quick_mode', {'user_id': user_id, 'enabled': enabled})

    async def update_download_quality(self, user_id: int, quality: str) -> Dict[str, Any]:
        return await self._request('update_download_quality', {'user_id': user_id, 'quality': quality})

    async def update_show_artwork(self, user_id: int, show: bool) -> Dict[str, Any]:
        return await self._request('update_show_artwork', {'user_id': user_id, 'show': show})

    async def update_auto_download(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self._request('update_auto_download', {'user_id': user_id, 'enabled': enabled})

    async def update_notifications(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self._request('update_notifications', {'user_id': user_id, 'enabled': enabled})

    async def log_search(self, user_id: int, search_type: str, search_term: str, result_count: int) -> Dict[str, Any]:
        return await self._request('log_search', {
            'user_id': user_id,
            'search_type': search_type,
            'search_term': search_term,
            'result_count': result_count
        })

    async def log_download(self, user_id: int, track_id: str, track_name: str, artist_name: str,
                           album_name: str = '', file_size: int = 0, download_source: str = 'youtube', quality: str = '192') -> Dict[str, Any]:
        return await self._request('log_download', {
            'user_id': user_id,
            'track_id': track_id,
            'track_name': track_name,
            'artist_name': artist_name,
            'album_name': album_name,
            'file_size': file_size,
            'download_source': download_source,
            'quality': quality
        })

    async def log_album_download(self, user_id: int, collection_id: str, collection_name: str,
                                 artist_name: str, total_tracks: int, successful_tracks: int,
                                 failed_tracks: int) -> Dict[str, Any]:
        return await self._request('log_album', {
            'user_id': user_id,
            'collection_id': collection_id,
            'collection_name': collection_name,
            'artist_name': artist_name,
            'total_tracks': total_tracks,
            'successful_tracks': successful_tracks,
            'failed_tracks': failed_tracks
        })

    async def get_required_channels(self) -> Dict[str, Any]:
        return await self._request('get_required_channels', {})

    async def get_broadcast_channels(self) -> Dict[str, Any]:
        return await self._request('get_broadcast_channels', {})

    async def get_active_users(self, limit: int = None) -> Dict[str, Any]:
        return await self._request('get_active_users', {'limit': limit})

    async def log_broadcast(self, message_id: str, channel_id: str, message_text: str,
                            sent_to: int, successful: int, failed: int) -> Dict[str, Any]:
        return await self._request('log_broadcast', {
            'message_id': message_id,
            'channel_id': channel_id,
            'message_text': message_text,
            'sent_to': sent_to,
            'successful': successful,
            'failed': failed
        })
