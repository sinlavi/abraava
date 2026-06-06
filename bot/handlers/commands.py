from balethon import Client
from balethon.objects import Message
from core.config import BOT_NAME, INFO_CHANNEL_ID
from utils.messages import send_message, edit_message
from bot.keyboards import get_settings_keyboard

async def start_command(bot: Client, message: Message):
    welcome_text = (
        f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
        f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n"
        f"فقط کافیه اسم آهنگ رو بگی، خودم بلدم چیکار کنم 😉\n\n"
        f"🆘 راهنما: /help"
    )
    if INFO_CHANNEL_ID:
        welcome_text += f"\n\n📢 *کانال اطلاع‌رسانی:* ble.ir/join/4T95Zt7P5X"
    await send_message(bot, message.chat.id, welcome_text)

async def help_command(bot: Client, message: Message):
    is_group = message.chat.type in ["group", "supergroup"]
    if is_group:
        await send_message(bot, message.chat.id, "🎵 *راهنمای استفاده*\n\nبرای جستجو، نام آهنگ/آلبوم/هنرمند را به همراه منشن ربات ارسال کنید.\nمثال: `@BotName آهنگ جدید`")
    else:
        await send_message(bot, message.chat.id,
            f"🛠 *راهنمای استفاده از {BOT_NAME}*\n\n"
            f"🔍 *دستورات جستجو:*\n"
            f"🔹 `/track [نام آهنگ]` - جستجوی آهنگ\n"
            f"🔹 `/album [نام آلبوم]` - جستجوی آلبوم\n"
            f"🔹 `/artist [نام هنرمند]` - جستجوی هنرمند\n"
            f"🔹 `/quick [نام آهنگ]` - دانلود سریع\n\n"
            f"⚙️ تنظیمات: /settings\n"
            f"📊 آمار: /stats"
        )

async def about_command(bot: Client, message: Message):
    await send_message(bot, message.chat.id,
        f"ℹ️ *درباره {BOT_NAME}*\n\n"
        f"ربات دانلود موزیک با قابلیت جستجو در iTunes و دانلود از YouTube Music\n\n"
        f"✨ *ویژگی‌ها:*\n"
        f"🔹 دانلود با کیفیت ۳۲۰/۱۹۲/۱۲۸ kbps\n"
        f"🔹 دانلود آلبوم به صورت یکجا\n"
        f"🔹 تگ‌گذاری خودکار (کاور و اطلاعات)\n"
        f"🔹 قابلیت غیرفعال کردن کاور برای سرعت بیشتر\n"
        f"🔹 دانلود خودکار در حالت سریع\n"
        f"🔹 سیستم سهمیه دانلود بر اساس کیفیت"
    )
