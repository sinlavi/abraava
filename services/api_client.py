import aiohttp
from typing import Dict, Any, List, Optional, Union
from core.logger import logger
from core.http_client import HttpClient
from core.config import PLATFORM, PROXY_3RAH

class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        session = await HttpClient.get_session(use_proxy=PROXY_3RAH)
        endpoint_path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
        url = f"{self.base_url}{endpoint_path}"

        req_headers = {
            'Authorization': f'Bearer {self.token}',
            'Platform': PLATFORM,
            'Content-Type': 'application/json'
        }
        if headers:
            req_headers.update(headers)

        try:
            method_upper = method.upper()
            kwargs = {'headers': req_headers}
            if params:
                kwargs['params'] = {k: v for k, v in params.items() if v is not None}
            if data and method_upper in ['POST', 'PUT', 'PATCH']:
                kwargs['json'] = data

            async with getattr(session, method_upper.lower())(url, **kwargs) as resp:
                try:
                    res_json = await resp.json()
                    if isinstance(res_json, dict):
                        return res_json
                    return {'success': resp.status < 400, 'data': res_json}
                except Exception:
                    text = await resp.text()
                    return {'success': resp.status < 400, 'message': text}
        except Exception as e:
            logger.error(f"API Client [{method} {endpoint}] failed: {e}")
            return {'success': False, 'message': str(e)}

    # Legacy Compatibility & Auth / User Profile Methods
    async def register_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request('POST', '/auth/register', data=user_data)

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        return await self._request('GET', '/user', params={'id': user_id})

    async def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        res = await self.get_user(user_id)
        if res.get('success') and 'user' in res:
            return {'success': True, 'data': res['user']}
        return res

    async def update_user_profile(self, user_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        payload = {'userId': user_id, **settings}
        return await self._request('PUT', '/user/profile', data=payload)

    async def update_quick_mode(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self.update_user_profile(user_id, {'quick_mode': enabled})

    async def update_download_quality(self, user_id: int, quality: str) -> Dict[str, Any]:
        return await self.update_user_profile(user_id, {'download_quality': quality})

    async def update_show_artwork(self, user_id: int, show: bool) -> Dict[str, Any]:
        return await self.update_user_profile(user_id, {'show_artwork': show})

    async def update_auto_download(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self.update_user_profile(user_id, {'auto_download': enabled})

    async def update_notifications(self, user_id: int, enabled: bool) -> Dict[str, Any]:
        return await self.update_user_profile(user_id, {'notifications': enabled})

    # Social Likes
    async def like_entity(self, user_id: int, entity_type: str, entity_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/like', data={'userId': user_id, 'entityType': entity_type, 'entityId': str(entity_id)})

    async def unlike_entity(self, user_id: int, entity_type: str, entity_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/like/remove', data={'userId': user_id, 'entityType': entity_type, 'entityId': str(entity_id)})

    async def get_like_status(self, entity_type: str, entity_id: Union[str, int], user_id: Optional[int] = None) -> Dict[str, Any]:
        params = {'entityType': entity_type, 'entityId': str(entity_id)}
        if user_id:
            params['userId'] = user_id
        return await self._request('GET', '/like/status', params=params)

    async def get_user_likes(self, user_id: int, entity_type: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        params = {'userId': user_id, 'limit': limit, 'offset': offset}
        if entity_type:
            params['entityType'] = entity_type
        return await self._request('GET', '/user/likes', params=params)

    # Comments
    async def get_comments(self, entity_type: str, entity_id: Union[str, int], limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return await self._request('GET', '/comments', params={'entityType': entity_type, 'entityId': str(entity_id), 'limit': limit, 'offset': offset})

    async def create_comment(self, user_id: int, entity_type: str, entity_id: Union[str, int], content: str, parent_id: Optional[int] = None) -> Dict[str, Any]:
        data = {'userId': user_id, 'entityType': entity_type, 'entityId': str(entity_id), 'content': content}
        if parent_id:
            data['parentId'] = parent_id
        return await self._request('POST', '/comment', data=data)

    async def delete_comment(self, user_id: int, comment_id: int) -> Dict[str, Any]:
        return await self._request('POST', '/comment/delete', data={'userId': user_id, 'commentId': comment_id})

    async def like_comment(self, user_id: int, comment_id: int) -> Dict[str, Any]:
        return await self._request('POST', '/comment/like', data={'userId': user_id, 'commentId': comment_id})

    # Playlists
    async def create_playlist(self, user_id: int, name: str, description: Optional[str] = None, is_public: bool = True) -> Dict[str, Any]:
        return await self._request('POST', '/playlist/create', data={'userId': user_id, 'name': name, 'description': description, 'isPublic': is_public})

    async def get_playlist(self, playlist_id: str) -> Dict[str, Any]:
        return await self._request('GET', '/playlist', params={'playlistId': playlist_id})

    async def get_my_playlists(self, user_id: int, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return await self._request('GET', '/my/playlists', params={'userId': user_id, 'limit': limit, 'offset': offset})

    async def add_track_to_playlist(self, user_id: int, playlist_id: str, track_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/playlist/add-track', data={'userId': user_id, 'playlistId': playlist_id, 'trackId': str(track_id)})

    async def remove_track_from_playlist(self, user_id: int, playlist_id: str, track_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/playlist/remove-track', data={'userId': user_id, 'playlistId': playlist_id, 'trackId': str(track_id)})

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        return await self._request('GET', '/playlist/tracks', params={'playlistId': playlist_id, 'limit': limit, 'offset': offset})

    # Library & History
    async def save_to_library(self, user_id: int, entity_type: str, entity_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/library/save', data={'userId': user_id, 'entityType': entity_type, 'entityId': str(entity_id)})

    async def remove_from_library(self, user_id: int, entity_type: str, entity_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/library/remove', data={'userId': user_id, 'entityType': entity_type, 'entityId': str(entity_id)})

    async def get_library(self, user_id: int, entity_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        params = {'userId': user_id, 'limit': limit, 'offset': offset}
        if entity_type:
            params['entityType'] = entity_type
        return await self._request('GET', '/library', params=params)

    async def record_history(self, user_id: int, track_id: Union[str, int], duration: int = 0) -> Dict[str, Any]:
        return await self._request('POST', '/history/record', data={'userId': user_id, 'trackId': str(track_id), 'duration': duration})

    async def get_history(self, user_id: int, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return await self._request('GET', '/history', params={'userId': user_id, 'limit': limit, 'offset': offset})

    async def clear_history(self, user_id: int) -> Dict[str, Any]:
        return await self._request('POST', '/history/clear', data={'userId': user_id})

    # Follows
    async def follow_artist(self, user_id: int, artist_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/follow/artist', data={'userId': user_id, 'artistId': str(artist_id)})

    async def unfollow_artist(self, user_id: int, artist_id: Union[str, int]) -> Dict[str, Any]:
        return await self._request('POST', '/unfollow/artist', data={'userId': user_id, 'artistId': str(artist_id)})

    async def get_my_artists(self, user_id: int) -> Dict[str, Any]:
        return await self._request('GET', '/my/artists', params={'userId': user_id})

    # Discovery
    async def get_popular(self, limit: int = 40, offset: int = 0, days: int = 7) -> Dict[str, Any]:
        return await self._request('GET', '/popular', params={'limit': limit, 'offset': offset, 'days': days})

    async def get_fresh(self, limit: int = 40) -> Dict[str, Any]:
        return await self._request('GET', '/fresh', params={'limit': limit})

    async def get_artist_tracks(self, artist_id: Union[str, int], page: int = 1, limit: int = 50, sort: str = 'album') -> Dict[str, Any]:
        return await self._request('GET', '/artist/tracks', params={'id': str(artist_id), 'page': page, 'limit': limit, 'sort': sort})

    async def suggest(self, query: str, limit: int = 10) -> Dict[str, Any]:
        return await self._request('GET', '/suggest', params={'q': query, 'limit': limit})

    # Analytics / Logging / System
    async def log_search(self, user_id: int, search_type: str, search_term: str, result_count: int) -> Dict[str, Any]:
        return await self._request('POST', '/history/record', data={
            'userId': user_id,
            'searchType': search_type,
            'searchTerm': search_term,
            'resultCount': result_count
        })

    async def log_download(self, user_id: int, track_id: str, track_name: str, artist_name: str,
                           album_name: str = '', file_size: int = 0, download_source: str = 'youtube', quality: str = '192') -> Dict[str, Any]:
        await self.record_history(user_id, track_id)
        return await self._request('POST', '/download/add', data={
            'userId': user_id,
            'trackId': track_id,
            'quality': quality,
            'status': 'completed'
        })

    async def log_album_download(self, user_id: int, collection_id: str, collection_name: str,
                                 artist_name: str, total_tracks: int, successful_tracks: int,
                                 failed_tracks: int) -> Dict[str, Any]:
        return await self._request('POST', '/download/add', data={
            'userId': user_id,
            'albumId': collection_id,
            'status': 'completed'
        })

    async def get_required_channels(self) -> Dict[str, Any]:
        return {'success': True, 'channels': []}

    async def get_broadcast_channels(self) -> Dict[str, Any]:
        return {'success': True, 'channels': []}

    async def get_active_users(self, limit: int = None) -> Dict[str, Any]:
        return await self._request('GET', '/stats', params={'limit': limit})

    async def log_broadcast(self, message_id: str, channel_id: str, message_text: str,
                            sent_to: int, successful: int, failed: int) -> Dict[str, Any]:
        return {'success': True}

    async def get_stats(self) -> Dict[str, Any]:
        return await self._request('GET', '/stats')
