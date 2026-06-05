from typing import Dict
from models.schemas import UserSettings, DownloadQuality
from services.api_client import APIClient
from core.logger import logger

class UserSettingsService:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.cache: Dict[int, UserSettings] = {}

    async def get_settings(self, user_id: int) -> UserSettings:
        if user_id in self.cache:
            return self.cache[user_id]

        try:
            res = await self.api_client.get_user_settings(user_id)
            if res.get('success'):
                data = res.get('data', {})
                quality_str = data.get('download_quality', '192')

                quality_map = {
                    "320": DownloadQuality.HIGH,
                    "192": DownloadQuality.MEDIUM,
                    "128": DownloadQuality.LOW,
                    "ask": DownloadQuality.ASK
                }

                settings = UserSettings(
                    user_id=user_id,
                    quick_mode=bool(data.get('quick_mode', False)),
                    download_quality=quality_map.get(quality_str, DownloadQuality.MEDIUM),
                    show_artwork=bool(data.get('show_artwork', True)),
                    auto_download=bool(data.get('auto_download', False)),
                    notifications=bool(data.get('notifications', True))
                )
                self.cache[user_id] = settings
                return settings
        except Exception as e:
            logger.error(f"Error loading user settings for {user_id}: {e}")

        default = UserSettings(user_id=user_id)
        self.cache[user_id] = default
        return default

    async def update_settings(self, user_id: int, **kwargs):
        settings = await self.get_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        # Sync with API
        if 'quick_mode' in kwargs:
            await self.api_client.update_quick_mode(user_id, kwargs['quick_mode'])
        if 'download_quality' in kwargs:
            quality = kwargs['download_quality']
            quality_str = quality.value if isinstance(quality, DownloadQuality) else str(quality)
            await self.api_client.update_download_quality(user_id, quality_str)
        if 'show_artwork' in kwargs:
            await self.api_client.update_show_artwork(user_id, kwargs['show_artwork'])
        if 'auto_download' in kwargs:
            await self.api_client.update_auto_download(user_id, kwargs['auto_download'])
        if 'notifications' in kwargs:
            await self.api_client.update_notifications(user_id, kwargs['notifications'])
