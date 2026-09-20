from typing import Dict, Any
from core.logger import logger
from models.schemas import UserSettings, DownloadQuality
from services.api_client import APIClient

class UserRegistrationService:
    def __init__(self, api_client: APIClient, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service

    async def register_user(self, message, user_id=None):
        user = getattr(message, 'author', None)
        chat_id = message.chat.id if message.chat else None

        if not chat_id or chat_id == 0:
            if user_id and user_id != 0:
                chat_id = user_id
            elif user and getattr(user, 'id', 0) != 0:
                chat_id = user.id

        if not chat_id or chat_id == 0:
            return

        settings = await self.user_settings_service.get_settings(chat_id)

        first_name = getattr(user, 'first_name', '') or ''
        last_name = getattr(user, 'last_name', '') or ''
        username = getattr(user, 'username', '') or ''
        if not username or len(username) < 3:
            username = f"user_{chat_id}"

        display_name = f"{first_name} {last_name}".strip() or f"User {chat_id}"

        user_data = {
            'chat_id': chat_id,
            'user_id': chat_id,
            'userId': chat_id,
            'email': f"user_{chat_id}@abraava.bot",
            'username': username,
            'password': f"pass_{chat_id}_secret",
            'displayName': display_name,
            'first_name': first_name,
            'last_name': last_name,
            'language_code': getattr(user, 'language_code', 'en') if user else 'en',
            'is_premium': getattr(user, 'is_premium', False) if user else False,
            'is_bot': getattr(user, 'is_bot', False) if user else False,
            'quick_mode': settings.quick_mode,
            'download_quality': settings.download_quality.value,
            'show_artwork': settings.show_artwork,
            'auto_download': settings.auto_download,
            'notifications': settings.notifications
        }

        result = await self.api_client.register_user(user_data)
        if result.get('success'):
            logger.info(f"User {chat_id} registered/updated successfully")
        else:
            logger.warning(f"Registration status for user {chat_id}: {result.get('message') or result.get('error')}")
