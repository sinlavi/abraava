from balethon import Client
from balethon.objects import Message, InlineKeyboardButton, InlineKeyboard
from core.config import BOT_NAME, INFO_CHANNEL_ID, REQUIRED_CHANNELS
from utils.messages import send_message, edit_message
from bot.keyboards import get_settings_keyboard, create_info_channel_button

async def start_command(bot: Client, message: Message):
    user_id = message.author.id
    welcome_text = (
        f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
        f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n"
        f"فقط کافیه اسم آهنگ رو بگی، خودم بلدم چیکار کنم 😉"
    )

    markup = []
    markup.append([InlineKeyboardButton(text="🆘 راهنما", callback_data=f"help_cmd:u{user_id}")])
    if INFO_CHANNEL_ID:
        markup.append([create_info_channel_button()])

    if REQUIRED_CHANNELS:
        for channel in REQUIRED_CHANNELS:
            markup.append([InlineKeyboardButton(text=f"📢 عضویت در {channel['name']}", url=f"https://ble.ir/{channel['username'].lstrip('@')}")])

    await send_message(bot, message.chat.id, welcome_text, reply_markup=InlineKeyboard(*markup) if markup else None, user_id=user_id)

async def help_command(bot: Client, message: Message, is_callback=False):
    user_id = message.author.id
    is_group = message.chat.type in ["group", "supergroup"]
    if is_group:
        help_text = (
            "🎵 *راهنمای استفاده در گروه‌ها*\n\n"
            "برای استفاده از ربات در گروه، کافیست نام آهنگ، آلبوم یا هنرمند مورد نظر خود را به همراه منشن ربات ارسال کنید.\n\n"
            "📌 *مثال:* ```@BotName محسن چاوشی```\n\n"
            "همچنین می‌توانید از دستورات زیر استفاده کنید:\n"
            "🔹 ```/track [نام]``` - جستجوی اختصاصی آهنگ\n"
            "🔹 ```/album [نام]``` - جستجوی اختصاصی آلبوم\n"
            "🔹 ```/artist [نام]``` - جستجوی اختصاصی هنرمند"
        )
    else:
        help_text = (
            f"🛠 *راهنمای جامع ربات {BOT_NAME}*\n\n"
            "خوش آمدید! برای پیدا کردن موسیقی مورد نظر خود می‌توانید به روش‌های زیر عمل کنید:\n\n"
            "🔍 *روش‌های جستجو:*\n"
            "۱. *جستجوی مستقیم:* کافیست نام آهنگ را بنویسید و ارسال کنید.\n"
            "۲. *استفاده از دستورات:* برای دقت بیشتر از دستورات زیر استفاده کنید:\n"
            "🔹 ```/track [نام آهنگ]```\n"
            "🔹 ```/album [نام آلبوم]```\n"
            "🔹 ```/artist [نام هنرمند]```\n"
            "🔹 ```/ytm [نام آهنگ]``` - جستجو در یوتیوب موزیک\n"
            "🔹 ```/sc [نام آهنگ]``` - جستجو در ساندکلاد\n"
            "🔹 ```/sp [نام آهنگ]``` - جستجو در اسپاتیفای\n"
            "🔹 ```/itunes [نام آهنگ]``` - جستجو در آیتیونز رسمی\n\n"
            "⚡ *قابلیت‌های کاربردی:*\n"
            "🔹 ```/quick [نام آهنگ]``` - دانلود فوری با بهترین کیفیت\n"
            "🔹 *لینک مستقیم:* ارسال لینک YouTube Music یا Apple Music جهت دانلود مستقیم.\n\n"
            "⚙️ *بخش تنظیمات:* با دستور /settings می‌توانید کیفیت دانلود، نمایش کاور و حالت دانلود خودکار را مدیریت کنید.\n"
            "📊 *آمار من:* با دستور /stats سهمیه باقی‌مانده و گزارش فعالیت خود را مشاهده کنید."
        )
    if is_callback:
        await edit_message(message, help_text, user_id=user_id)
    else:
        await send_message(bot, message.chat.id, help_text, user_id=user_id)

async def about_command(bot: Client, message: Message):
    user_id = message.author.id
    about_text = (
        f"ℹ️ *درباره پروژه {BOT_NAME}*\n\n"
        f"ربات {BOT_NAME} پیشرفته‌ترین ابزار جستجو و دانلود موسیقی در پیام‌رسان بله است که با اتصال به دیتابیس‌های جهانی همچون iTunes و YouTube Music، بهترین تجربه را برای شما فراهم می‌کند.\n\n"
        "✨ *ویژگی‌های برجسته:*\n"
        "🔹 *کیفیت برتر:* امکان انتخاب کیفیت ۳۲۰، ۱۹۲ و ۱۲۸ kbps.\n"
        "🔹 *آلبوم کامل:* دانلود تمامی قطعات یک آلبوم به صورت یکجا و خودکار.\n"
        "🔹 *تگ‌گذاری هوشمند:* ثبت خودکار نام اثر، هنرمند، آلبوم و کاور با کیفیت بالا روی فایل صوتی.\n"
        "🔹 *مینی اپ اختصاصی:* دارای مینی اپ پلیر جهت پخش آنلاین و مدیریت لیست پخش.\n"
        "🔹 *سرعت فوق‌العاده:* سیستم پردازش موازی و کشینگ هوشمند جهت تسریع در ارسال فایل‌ها.\n\n"
        "💎 طراحی شده برای عاشقان موسیقی."
    )
    await send_message(bot, message.chat.id, about_text, user_id=user_id)
