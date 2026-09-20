from balethon import Client
from balethon.objects import Message, InlineKeyboardButton, InlineKeyboard
from core.config import BOT_NAME, INFO_CHANNEL_ID, REQUIRED_CHANNELS, DEEP_LINK_BASE
from utils.messages import send_message, edit_message
from bot.keyboards import get_settings_keyboard, create_info_channel_button, get_my_hub_keyboard, create_close_button, create_pagination_row

async def start_command(bot: Client, message: Message):
    welcome_text = (
        f"🎵 *به ربات موسیقی {BOT_NAME} خوش آمدید*\n\n"
        f"من اینجام تا آهنگ‌های مورد علاقت رو برات پیدا کنم و بفرستم.\n"
        f"فقط کافیه اسم آهنگ رو بگی، خودم بلدم چیکار کنم 😉\n\n"
        f"🌟 *بخش‌های جدید:*\n"
        f"🔹 /my - مرکز مدیریت شخصی (کتابخانه، لیست‌های پخش، هنرمندان)\n"
        f"🔹 /popular - داغ‌ترین و محبوب‌ترین آهنگ‌ها\n"
        f"🔹 /fresh - تازه‌ترین آهنگ‌های اضافه شده"
    )

    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    markup = []
    markup.append([InlineKeyboardButton(text="👤 بخش شخصی من (/my)", callback_data=f"my_hub:u{user_id}")])
    markup.append([InlineKeyboardButton(text="🔥 محبوب‌ترین‌ها", callback_data=f"popular_tracks:u{user_id}"),
                   InlineKeyboardButton(text="🆕 تازه اضافه شده", callback_data=f"fresh_tracks:u{user_id}")])
    markup.append([InlineKeyboardButton(text="🆘 راهنما", callback_data=f"help_cmd:u{user_id}")])
    if INFO_CHANNEL_ID:
        markup.append([create_info_channel_button()])

    if REQUIRED_CHANNELS:
        for channel in REQUIRED_CHANNELS:
            markup.append([InlineKeyboardButton(text=f"📢 عضویت در {channel['name']}", url=f"https://ble.ir/{channel['username'].lstrip('@')}")])

    await send_message(bot, message.chat.id, welcome_text, reply_markup=InlineKeyboard(*markup) if markup else None)

async def help_command(bot: Client, message: Message, is_callback=False):
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
            "🔹 ```/sc [نام آهنگ]``` - جستجو در ساندکلاد\n\n"
            "🌟 *بخش‌های تعاملی و شخصی:*\n"
            "🔹 ```/my``` - هاب شخصی من (کتابخانه، لیست‌های پخش، هنرمندان و تاریخچه)\n"
            "🔹 ```/popular``` - آهنگ‌های ترند و محبوب هفته\n"
            "🔹 ```/fresh``` - آهنگ‌های تازه اضافه شده\n"
            "🔹 ```/playlists``` - مدیریت و ساخت لیست‌های پخش شخصی\n"
            "🔹 ```/history``` - مشاهده و مدیریت تاریخچه شنیداری\n\n"
            "⚡ *قابلیت‌های کاربردی:*\n"
            "🔹 ```/quick [نام آهنگ]``` - دانلود فوری با بهترین کیفیت\n"
            "🔹 *لینک مستقیم:* ارسال لینک YouTube Music یا Apple Music جهت دانلود مستقیم.\n\n"
            "⚙️ *تنظیمات:* دستور /settings جهت تغییر کیفیت دانلود و حالت دانلود خودکار."
        )
    if is_callback:
        message = await edit_message(message, help_text)
    else:
        await send_message(bot, message.chat.id, help_text)

async def about_command(bot: Client, message: Message):
    about_text = (
        f"ℹ️ *درباره پروژه {BOT_NAME}*\n\n"
        f"ربات {BOT_NAME} پیشرفته‌ترین ابزار جستجو، پخش و دانلود موسیقی با اتصال به جدیدترین API ابرآوا (`mm.3rah.ir/api`) است.\n\n"
        "✨ *ویژگی‌های برجسته:*\n"
        "🔹 *امکانات اجتماعی:* پسندیدن آهنگ‌ها (Like)، نظرات، و دنبال کردن هنرمندان محبوب.\n"
        "🔹 *کتابخانه و لیست پخش شخصی:* ذخیره‌سازی قطعات دلخواه و ساخت پлей‌لیست اختصاصی.\n"
        "🔹 *موسیقی‌های برتر و تازه:* دسترسی به آهنگ‌های محبوب روز و جدیدترین انتشارها.\n"
        "🔹 *کیفیت برتر:* امکان انتخاب کیفیت ۳۲۰، ۱۹۲ و ۱۲۸ kbps.\n"
        "🔹 *آلبوم کامل:* دانلود تمامی قطعات یک آلبوم به صورت یکجا و خودکار.\n"
        "🔹 *تگ‌گذاری هوشمند:* ثبت خودکار متادیتا و کاور با کیفیت بالا روی فایل صوتی.\n"
        "🔹 *مینی اپ پلیر:* پخش آنلاین و مرور موسیقی در محیط مینی اپ بله.\n\n"
        "💎 طراحی شده برای عاشقان موسیقی."
    )
    await send_message(bot, message.chat.id, about_text)

async def my_command(bot: Client, message: Message):
    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    text = (
        f"👤 *مرکز مدیریت شخصی کاربر*\n\n"
        f"از این بخش می‌توانید به کتابخانه، لیست‌های پخش شخصی، هنرمندان دنبال شده و تاریخچه پخش خود دسترسی داشته باشید."
    )
    await send_message(bot, message.chat.id, text, reply_markup=get_my_hub_keyboard(user_id))

async def popular_command(bot: Client, message: Message, api_client):
    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    msg = await send_message(bot, message.chat.id, "🔄 *در حال دریافت محبوب‌ترین آهنگ‌ها...*")
    res = await api_client.get_popular(limit=10)
    if not res.get("success") or not res.get("results"):
        await edit_message(msg, "❌ متأسفانه در حال حاضر فهرستی یافت نشد.")
        return

    tracks = res["results"]
    text = "🔥 *محبوب‌ترین و پربازدیدترین آهنگ‌ها:*\n\n"
    markup_rows = []
    for i, t in enumerate(tracks, 1):
        tid = t.get("trackId")
        tname = t.get("trackName", "نامشخص")
        aname = t.get("artistName", "نامشخص")
        views = t.get("views", 0)
        views_str = f" ({views} بازدید)" if views else ""
        text += f"{i}. [{tname} - {aname}]({DEEP_LINK_BASE}track_{tid}){views_str}\n"
        markup_rows.append([InlineKeyboardButton(text=f"{i}. {tname[:30]} - {aname[:20]}", callback_data=f"track:{tid}:u{user_id}")])

    markup_rows.append([create_close_button(user_id)])
    await edit_message(msg, text, reply_markup=InlineKeyboard(*markup_rows))

async def fresh_command(bot: Client, message: Message, api_client):
    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    msg = await send_message(bot, message.chat.id, "🔄 *در حال دریافت جدیدترین آهنگ‌ها...*")
    res = await api_client.get_fresh(limit=10)
    if not res.get("success") or not res.get("results"):
        await edit_message(msg, "❌ متأسفانه در حال حاضر فهرستی یافت نشد.")
        return

    tracks = res["results"]
    text = "🆕 *تازه‌ترین آهنگ‌های اضافه شده:*\n\n"
    markup_rows = []
    for i, t in enumerate(tracks, 1):
        tid = t.get("trackId")
        tname = t.get("trackName", "نامشخص")
        aname = t.get("artistName", "نامشخص")
        text += f"{i}. [{tname} - {aname}]({DEEP_LINK_BASE}track_{tid})\n"
        markup_rows.append([InlineKeyboardButton(text=f"{i}. {tname[:30]} - {aname[:20]}", callback_data=f"track:{tid}:u{user_id}")])

    markup_rows.append([create_close_button(user_id)])
    await edit_message(msg, text, reply_markup=InlineKeyboard(*markup_rows))

async def playlists_command(bot: Client, message: Message, api_client):
    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    msg = await send_message(bot, message.chat.id, "🔄 *در حال دریافت لیست‌های پخش...*")
    res = await api_client.get_my_playlists(user_id)
    playlists = res.get("playlists", []) if res.get("success") else []

    text = "🎶 *لیست‌های پخش شخصی شما:*\n\n"
    markup_rows = []
    if not playlists:
        text += "شما هنوز هیچ لیست پخشی نساخته‌اید."
    else:
        for p in playlists:
            pid = p.get("playlistId")
            pname = p.get("name")
            tcount = p.get("trackCount", 0)
            text += f"🔹 *{pname}* ({tcount} آهنگ)\n"
            markup_rows.append([InlineKeyboardButton(text=f"🎶 {pname} ({tcount} قطعه)", callback_data=f"view_pl:{pid}:u{user_id}")])

    markup_rows.append([InlineKeyboardButton(text="➕ ساخت لیست پخش جدید", callback_data=f"create_pl_prompt:u{user_id}")])
    markup_rows.append([create_close_button(user_id)])
    await edit_message(msg, text, reply_markup=InlineKeyboard(*markup_rows))

async def history_command(bot: Client, message: Message, api_client):
    user_id = message.author.id
    if (not user_id or user_id == 0) and message.chat.type == "private":
        user_id = message.chat.id

    msg = await send_message(bot, message.chat.id, "🔄 *در حال دریافت تاریخچه پخش...*")
    res = await api_client.get_history(user_id, limit=10)
    history = res.get("history", []) if res.get("success") else []

    text = "📜 *تاریخچه شنیداری و دانلودهای اخیر شما:*\n\n"
    markup_rows = []
    if not history:
        text += "تاریخچه‌ای یافت نشد."
    else:
        for i, item in enumerate(history, 1):
            tid = item.get("trackId")
            time_str = item.get("playedAt", "")[:16]
            text += f"{i}. کد track: `{tid}` — {time_str}\n"
            markup_rows.append([InlineKeyboardButton(text=f"🎵 آهنگ {tid}", callback_data=f"track:{tid}:u{user_id}")])

        markup_rows.append([InlineKeyboardButton(text="🗑️ پاک‌سازی تاریخچه", callback_data=f"clear_history_prompt:u{user_id}")])

    markup_rows.append([create_close_button(user_id)])
    await edit_message(msg, text, reply_markup=InlineKeyboard(*markup_rows))
