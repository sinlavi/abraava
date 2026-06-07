from typing import Dict, Any
from core.logger import logger
from models.schemas import UserSettings, DownloadQuality
from services.api_client import APIClient
from core.platform import MessageAdapter

class UserRegistrationService:
    def __init__(self, api_client: APIClient, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service

    async def register_user(self, message: MessageAdapter):
        user_id = message.user_id
        if not user_id: return

        settings = await self.user_settings_service.get_settings(user_id)

        # We try to get extra user info from raw message
        raw_user = None
        from core.config import PLATFORM, Platform
        if PLATFORM == Platform.BALE:
            raw_user = message.raw.author
        else:
            raw_user = message.raw.sender

        user_data = {
            'user_id': user_id,
            'username': getattr(raw_user, 'username', '') or '',
            'first_name': getattr(raw_user, 'first_name', '') or '',
            'last_name': getattr(raw_user, 'last_name', '') or '',
            'language_code': getattr(raw_user, 'language_code', 'en'),
            'is_premium': getattr(raw_user, 'is_premium', False),
            'is_bot': message.author_is_bot,
            'user_agent': message.text or '',
            'ip_address': '',
            'quick_mode': settings.quick_mode,
            'download_quality': settings.download_quality.value,
            'show_artwork': settings.show_artwork,
            'auto_download': settings.auto_download,
            'notifications': settings.notifications
        }

        result = await self.api_client.register_user(user_data)
        if result.get('success'):
            logger.info(f"User {user_id} registered/updated")
        else:
            logger.error(f"Failed to register user {user_id}: {result.get('message')}")
