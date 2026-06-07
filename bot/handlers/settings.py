from core.platform import MessageAdapter, InlineKeyboardButton, InlineKeyboard
from bot.keyboards import get_settings_keyboard, create_close_button
from utils.messages import send_message, edit_message
from models.schemas import DownloadQuality
import logging

logger = logging.getLogger("ABRAAVA:SETTINGS")

async def settings_command(bot, message: MessageAdapter, user_settings_service):
    user_id = message.user_id
    settings = await user_settings_service.get_settings(user_id)

    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"

    from core.config import BOT_NAME
    text = (
        f"⚙️ *پنل تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت جستجوی سریع:* {'✅ فعال' if settings.quick_mode else '❌ غیرفعال'}\n"
        f"🎵 *کیفیت پیش‌فرض:* {quality_text}\n"
        f"🖼️ *نمایش کاور آهنگ:* {'✅ فعال' if settings.show_artwork else '❌ غیرفعال'}\n"
        f"📥 *دانلود خودکار:* {'✅ فعال' if settings.auto_download else '❌ غیرفعال'}\n"
        f"🔔 *اعلان‌های سیستم:* {'✅ فعال' if settings.notifications else '❌ غیرفعال'}\n"
        f"\n💡 *راهنما:* برای تغییر هر مورد، روی دکمه مربوطه کلیک کنید."
    )

    markup = get_settings_keyboard(settings.quick_mode, quality_text, settings.show_artwork, settings.auto_download, settings.notifications, user_id=user_id)
    await send_message(bot, message.chat_id, text, reply_markup=InlineKeyboard(*markup))

async def stats_command(bot, message: MessageAdapter, api_client, rate_limiter, download_rate_limiter):
    user_id = message.user_id
    await stats_command_logic(bot, message, user_id, api_client, rate_limiter, download_rate_limiter)

async def stats_command_logic(bot, message, user_id, api_client, rate_limiter, download_rate_limiter):
    # This logic was likely intended to be more complex, but for now:
    text = "📊 *آمار فعالیت شما:*\n\n(بزودی)"
    markup = [[create_close_button(user_id)]]

    if isinstance(message, MessageAdapter):
        await send_message(bot, message.chat_id, text, reply_markup=InlineKeyboard(*markup))
    else:
        # If it was called from callback
        await edit_message(message, text, reply_markup=InlineKeyboard(*markup))
