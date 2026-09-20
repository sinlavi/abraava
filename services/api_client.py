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
        endpoint_path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
        url = f"{self.base_url}{endpoint_path}"

        req_headers = {
            'Authorization': f'Bearer {self.token}',
            'Platform': PLATFORM,
            'Content-Type': 'application/json'
        }
        if headers:
            req_headers.update(headers)

        method_upper = method.upper()

        for use_proxy in ([PROXY_3RAH, False] if PROXY_3RAH else [False]):
            try:
                session = await HttpClient.get_session(use_proxy=use_proxy)
                kwargs = {'headers': req_headers}
                if params:
                    kwargs['params'] = {k: v for k, v in params.items() if v is not None}
                if data and method_upper in ['POST', 'PUT', 'PATCH']:
                    kwargs['json'] = data

                async with getattr(session, method_upper.lower())(url, **kwargs) as resp:
                    if resp.status == 503 and use_proxy:
                        logger.warning(f"API Client [{method} {endpoint}] received 503 via proxy, retrying direct...")
                        continue
                    try:
                        res_json = await resp.json()
                        if isinstance(res_json, dict):
                            return res_json
                        return {'success': resp.status < 400, 'data': res_json}
                    except Exception:
                        text = await resp.text()
                        return {'success': resp.status < 400, 'message': text}
            except Exception as e:
                logger.warning(f"API Client [{method} {endpoint}] attempt (use_proxy={use_proxy}) failed: {e}")
                if use_proxy:
                    continue
                return {'success': False, 'message': str(e)}

        return {'success': False, 'message': 'API request failed after retries'}

    # Auth & Registration
    async def register_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._request('POST', '/auth/register', data=user_data)
        if not res.get('success'):
            msg = str(res.get('error') or res.get('message') or '').lower()
            if 'already' in msg or 'taken' in msg:
                identifier = user_data.get('email') or user_data.get('username')
                password = user_data.get('password')
                login_res = await self._request('POST', '/auth/login', data={'identifier': identifier, 'password': password})
                if login_res.get('success'):
                    return login_res
                return {'success': True, 'message': 'User already registered'}
        return res

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
