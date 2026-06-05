from typing import Dict, Any
from core.logger import logger
from models.schemas import UserSettings, DownloadQuality
from services.api_client import APIClient

class UserRegistrationService:
    def __init__(self, api_client: APIClient, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service

    async def register_user(self, message):
        user = message.author
        settings = await self.user_settings_service.get_settings(user.id)

        user_data = {
            'user_id': user.id,
            'username': user.username or '',
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'language_code': getattr(user, 'language_code', 'en'),
            'is_premium': getattr(user, 'is_premium', False),
            'is_bot': getattr(user, 'is_bot', False),
            'user_agent': message.content or '',
            'ip_address': '',
            'quick_mode': settings.quick_mode,
            'download_quality': settings.download_quality.value,
            'show_artwork': settings.show_artwork,
            'auto_download': settings.auto_download,
            'notifications': settings.notifications
        }

        result = await self.api_client.register_user(user_data)
        if result.get('success'):
            logger.info(f"User {user.id} registered/updated")
        else:
            logger.error(f"Failed to register user {user.id}: {result.get('message')}")
