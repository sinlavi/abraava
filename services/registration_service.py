from core.logger import logger

class UserRegistrationService:
    def __init__(self, api_client, user_settings_service):
        self.api_client = api_client
        self.user_settings_service = user_settings_service

    async def register_user(self, message, user_id=None):
        if user_id is None: user_id = message.author_id
        if not user_id or user_id == 0: return
        settings = await self.user_settings_service.get_settings(user_id)
        user_data = {
            'user_id': user_id,
            'quick_mode': settings.quick_mode,
            'download_quality': settings.download_quality.value,
            'show_artwork': settings.show_artwork,
            'auto_download': settings.auto_download,
            'notifications': settings.notifications
        }
        result = await self.api_client.register_user(user_data)
        if result.get('success'): logger.info(f"User {user_id} registered/updated")
        else: logger.error(f"Failed to register user {user_id}: {result.get('message')}")
