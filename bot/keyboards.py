from balethon.objects import InlineKeyboard, InlineKeyboardButton
from core.config import FOOTER, INFO_CHANNEL_USERNAME

def create_close_button(user_id: int = None) -> InlineKeyboardButton:
    cb = f"close:u{user_id}" if user_id else "close"
    return InlineKeyboardButton(text="❌ بستن", callback_data=cb)

def create_cancel_button(task_id: str, user_id: int = None) -> InlineKeyboardButton:
    cb = f"cancel_task:{task_id}"
    if user_id: cb += f":u{user_id}"
    return InlineKeyboardButton(text="⏹️ توقف", callback_data=cb)

def create_info_channel_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="📢 کانال اطلاع‌رسانی", url=f"https://ble.ir/{INFO_CHANNEL_USERNAME.lstrip('@')}")

def create_retry_button(callback_data: str, button_text: str = "🔄 تلاش مجدد", user_id: int = None) -> InlineKeyboardButton:
    cb = callback_data if callback_data.startswith("retry:") else f"retry:{callback_data}"
    if user_id: cb += f":u{user_id}"
    return InlineKeyboardButton(text=button_text, callback_data=cb)

def create_pagination_row(callback_prefix: str, current_page: int, total_pages: int, user_id: int = None):
    if total_pages <= 1: return []
    buttons = []

    suffix = f":u{user_id}" if user_id else ""

    # Following RTL flow: [First ⏭️] [Prev ▶️] [Page] [Next ◀️] [Last ⏮️]
    if current_page > 1:
        buttons.append(InlineKeyboardButton(text="⏭️", callback_data=f"{callback_prefix}:1{suffix}"))
        buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"{callback_prefix}:{current_page - 1}{suffix}"))

    buttons.append(InlineKeyboardButton(text=f"{current_page} از {total_pages}", callback_data="ignore"))

    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"{callback_prefix}:{current_page + 1}{suffix}"))
        buttons.append(InlineKeyboardButton(text="⏮️", callback_data=f"{callback_prefix}:{total_pages}{suffix}"))

    return buttons

def get_settings_keyboard(quick_mode, quality_text, show_artwork, auto_download, notifications, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    return [
        [InlineKeyboardButton(text=f"{'✅' if quick_mode else '❌'} ⚡ حالت سریع", callback_data=f"menu_quick_mode{suffix}")],
        [InlineKeyboardButton(text=f"🎵 کیفیت دانلود ({quality_text})", callback_data=f"show_quality_menu{suffix}")],
        [InlineKeyboardButton(text=f"{'✅' if show_artwork else '❌'} 🖼️ نمایش کاور", callback_data=f"menu_artwork{suffix}")],
        [InlineKeyboardButton(text=f"{'✅' if auto_download else '❌'} 📥 دانلود خودکار", callback_data=f"menu_auto_download{suffix}")],
        [InlineKeyboardButton(text=f"{'✅' if notifications else '❌'} 🔔 دریافت اعلان", callback_data=f"menu_notifications{suffix}")]
    ]

def get_quality_keyboard(current_quality, user_id: int = None):
    from models.schemas import DownloadQuality
    suffix = f":u{user_id}" if user_id else ""
    return [
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.HIGH else ''}🎵 ۳۲۰ kbps", callback_data=f"set_quality:320{suffix}")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.MEDIUM else ''}🎶 ۱۹۲ kbps", callback_data=f"set_quality:192{suffix}")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.LOW else ''}🎧 ۱۲۸ kbps", callback_data=f"set_quality:128{suffix}")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.ASK else ''}❓ هر بار بپرس", callback_data=f"set_quality:ask{suffix}")],
        [InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data=f"back_to_settings{suffix}")]
    ]

def get_confirmation_keyboard(setting_type, new_value, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    return [
        [
            InlineKeyboardButton(text="✅ بله، تغییر کن", callback_data=f"confirm_{setting_type}:{int(new_value)}{suffix}"),
            InlineKeyboardButton(text="❌ خیر، انصراف", callback_data=f"back_to_settings{suffix}")
        ]
    ]
