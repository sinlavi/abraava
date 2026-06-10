from core.config import BOT_NAME
from utils.messages import send_message, edit_message
from bot.keyboards import get_settings_keyboard, get_quality_keyboard
from models.schemas import DownloadQuality

async def settings_command(bot, message, user_settings_service):
    user_id = getattr(message.author, 'id', getattr(message, 'sender_id', None))
    settings = await user_settings_service.get_settings(user_id)

    quality_text = "هر بار بپرس" if settings.download_quality == DownloadQuality.ASK else f"{settings.download_quality.value} kbps"

    settings_text = (
        f"⚙️ *تنظیمات ربات {BOT_NAME}*\n\n"
        f"⚡ *حالت سریع:* {'فعال' if settings.quick_mode else 'غیرفعال'}\n"
        f"🎵 *کیفیت دانلود:* {quality_text}\n"
        f"🖼️ *نمایش کاور:* {'فعال' if settings.show_artwork else 'غیرفعال'}\n"
        f"⚡ *دانلود خودکار:* {'فعال' if settings.auto_download else 'غیرفعال'}\n"
        f"🔔 *دریافت اعلان:* {'فعال' if settings.notifications else 'غیرفعال'}\n\n"
        f"📊 برای مشاهده آمار دقیق، روی دکمه «آمار من» کلیک کنید."
    )

    markup = get_settings_keyboard(
        settings.quick_mode, quality_text, settings.show_artwork,
        settings.auto_download, settings.notifications
    )

    await send_message(bot, message.chat.id, settings_text, reply_markup=markup)

async def stats_command_logic(bot, message, user_id, api_client, rate_limiter, download_rate_limiter):
    remaining_search = rate_limiter.get_user_remaining(user_id)
    remaining_download = download_rate_limiter.get_remaining(user_id)

    user_data = await api_client.get_user(user_id)
    total_searches = user_data.get('data', {}).get('total_searches', 0) if user_data.get('success') else 0
    total_downloads = user_data.get('data', {}).get('total_downloads', 0) if user_data.get('success') else 0

    text = (
        f"📊 *گزارش فعالیت و سهمیه شما*\n\n"
        f"⏳ *سهمیه باقی‌مانده (امروز):*\n"
        f"🔍 جستجو: ```{remaining_search}``` از ```{rate_limiter.max_requests}```\n"
        f"⬇️ دانلود: ```{remaining_download}``` از ```{download_rate_limiter.max_downloads}```\n\n"
        f"📈 *آمار کلی فعالیت شما:*\n"
        f"🔹 کل جستجوها: ```{total_searches}``` مورد\n"
        f"🔹 کل دانلودها: ```{total_downloads}``` فایل\n\n"
        f"✨ ممنون که از ما استفاده می‌کنید!"
    )

    from bot.keyboards import create_close_button
    message = await edit_message(message, text, reply_markup=[[create_close_button()]])

async def stats_command(bot, message, api_client, rate_limiter, download_rate_limiter):
    user_id = getattr(message.author, 'id', getattr(message, 'sender_id', None))
    remaining_search = rate_limiter.get_user_remaining(user_id)
    remaining_download = download_rate_limiter.get_remaining(user_id)

    user_data = await api_client.get_user(user_id)
    total_searches = user_data.get('data', {}).get('total_searches', 0) if user_data.get('success') else 0
    total_downloads = user_data.get('data', {}).get('total_downloads', 0) if user_data.get('success') else 0

    text = (
        f"📊 *گزارش فعالیت و سهمیه شما*\n\n"
        f"⏳ *سهمیه باقی‌مانده (امروز):*\n"
        f"🔍 جستجو: ```{remaining_search}``` از ```{rate_limiter.max_requests}```\n"
        f"⬇️ دانلود: ```{remaining_download}``` از ```{download_rate_limiter.max_downloads}```\n\n"
        f"📈 *آمار کلی فعالیت شما:*\n"
        f"🔹 کل جستجوها: ```{total_searches}``` مورد\n"
        f"🔹 کل دانلودها: ```{total_downloads}``` فایل\n\n"
        f"✨ ممنون که از ما استفاده می‌کنید!"
    )
    await send_message(bot, message.chat.id, text)
