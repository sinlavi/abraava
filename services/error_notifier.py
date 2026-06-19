import time
from core.logger import logger
from core.config import INFO_CHANNEL_ID, PLATFORM

class UploadErrorNotifier:
    def __init__(self, api_client):
        self.api_client = api_client
        self.notification_message_id = None
        self.error_active = False
        self.last_error_time = 0
        self.error_cooldown = 300

    async def notify_upload_error(self, bot, error_message: str = "", album_download_callback: callable = None):
        if not INFO_CHANNEL_ID: return
        current_time = time.time()
        if self.error_active or current_time - self.last_error_time < self.error_cooldown:
            if album_download_callback:
                try: await album_download_callback()
                except Exception as e: logger.error(f"Error in album download callback: {e}")
            return
        self.last_error_time = current_time
        platform_name = 'تلگرام' if PLATFORM == "telegram" else 'بله'
        notification_text = (
            f"⚠️ *اختلال در سرویس آپلود {platform_name}* ⚠️\n\n"
            f"در حال حاضر سرویس آپلود فایل پیام‌رسان {platform_name} با مشکل مواجه شده است.\n"
            "این مشکل احتمالا از سمت پیام‌رسان می‌باشد، به محض رفع مشکل، ربات به حالت عادی بازخواهد گشت.\n\n"
            "✅ به محض رفع مشکل، این پیام حذف خواهد شد.\n\n#اختلال\n\n@abraava\n@abraava_bot"
        )
        try:
            msg = await bot.send_message(INFO_CHANNEL_ID, notification_text)
            self.notification_message_id = msg.id
            self.error_active = True
            if album_download_callback:
                try: await album_download_callback()
                except Exception as e: logger.error(f"Error in album download callback: {e}")
        except Exception as e: logger.error(f"Failed to send upload error notification: {e}")

    async def clear_upload_error_notification(self, bot):
        if not INFO_CHANNEL_ID or not self.error_active: return
        try:
            await bot.delete_message(INFO_CHANNEL_ID, self.notification_message_id)
        except Exception as e:
            if "not found" not in str(e).lower(): logger.error(f"Failed to delete error notification: {e}")
        finally:
            self.error_active = False
            self.notification_message_id = None

    async def check_and_clear_if_resolved(self, bot, test_success: bool = False):
        if self.error_active and test_success: await self.clear_upload_error_notification(bot)
