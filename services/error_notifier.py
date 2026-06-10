import time
from typing import Optional, List, Dict
from core.logger import logger
from services.api_client import APIClient
from core.config import INFO_CHANNEL_ID, PLATFORM

class BaleUploadErrorNotifier:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.notification_message_id = None
        self.error_active = False
        self.last_error_time = 0
        self.error_cooldown = 300

    async def notify_upload_error(self, bot, error_message: str = "", album_download_callback: callable = None):
        if not INFO_CHANNEL_ID:
            return

        current_time = time.time()

        if self.error_active:
            logger.info("Upload error notification already active")
            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")
            return

        if current_time - self.last_error_time < self.error_cooldown:
            logger.info(f"Upload error notification on cooldown")
            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")
            return

        self.last_error_time = current_time

        messenger_name = "تلگرام" if PLATFORM == "telegram" else "بله"
        notification_text = (
            f"⚠️ *اختلال در سرویس آپلود {messenger_name}* ⚠️\n\n"
            f"در حال حاضر سرویس آپلود فایل پیام‌رسان {messenger_name} با مشکل مواجه شده است.\n"
            f"این مشکل احتمالا از سمت {messenger_name} می‌باشد، به محض رفع مشکل، ربات به حالت عادی بازخواهد گشت.\n\n"
            "✅ به محض رفع مشکل، این پیام حذف خواهد شد.\n\n"
            "#اختلال\n\n@abraava\n@abraava_bot"
        )

        try:
            from utils.messages import send_message
            msg = await send_message(bot, INFO_CHANNEL_ID, notification_text, no_close=True)
            self.notification_message_id = getattr(msg, "id", None)
            self.error_active = True
            logger.warning(f"Bale upload error notification sent")

            if album_download_callback:
                try:
                    await album_download_callback()
                except Exception as e:
                    logger.error(f"Error in album download callback: {e}")

        except Exception as e:
            logger.error(f"Failed to send upload error notification: {e}")

    async def clear_upload_error_notification(self, bot):
        if not INFO_CHANNEL_ID or not self.error_active:
            return

        try:
            if hasattr(bot, "delete_message"):
                await bot.delete_message(INFO_CHANNEL_ID, self.notification_message_id)
            else:
                from core.bot_client import get_bot_client
                client = get_bot_client()
                await client.delete_message(INFO_CHANNEL_ID, self.notification_message_id)
            logger.info("Upload error notification cleared")
        except Exception as e:
            if "message not found" not in str(e).lower():
                logger.error(f"Failed to delete error notification: {e}")
        finally:
            self.error_active = False
            self.notification_message_id = None

    async def check_and_clear_if_resolved(self, bot, test_success: bool = False):
        if self.error_active and test_success:
            await self.clear_upload_error_notification(bot)
