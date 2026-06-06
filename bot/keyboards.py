from balethon.objects import InlineKeyboard, InlineKeyboardButton
from core.config import FOOTER, INFO_CHANNEL_USERNAME

def create_close_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="❌ بستن", callback_data="close")

def create_cancel_button(task_id: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="⏹️ توقف", callback_data=f"cancel_task:{task_id}")

def create_info_channel_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="📢 کانال اطلاع‌رسانی", url=f"https://ble.ir/{INFO_CHANNEL_USERNAME.lstrip('@')}")

def create_retry_button(callback_data: str, button_text: str = "🔄 تلاش مجدد") -> InlineKeyboardButton:
    cb = callback_data if callback_data.startswith("retry:") else f"retry:{callback_data}"
    return InlineKeyboardButton(text=button_text, callback_data=cb)

def create_pagination_row(callback_prefix: str, current_page: int, total_pages: int):
    if total_pages <= 1: return []
    buttons = []

    # Swapped positions for RTL layout
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(text="⏭️", callback_data=f"{callback_prefix}:{total_pages}"))
        buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"{callback_prefix}:{current_page + 1}"))

    buttons.append(InlineKeyboardButton(text=f"{current_page} از {total_pages}", callback_data="ignore"))

    if current_page > 1:
        buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"{callback_prefix}:{current_page - 1}"))
        buttons.append(InlineKeyboardButton(text="⏮️", callback_data=f"{callback_prefix}:1"))

    return buttons

def get_settings_keyboard(quick_mode, quality_text, show_artwork, auto_download, notifications):
    return [
        [InlineKeyboardButton(text=f"{'✅' if quick_mode else '❌'} ⚡ حالت سریع", callback_data="menu_quick_mode")],
        [InlineKeyboardButton(text=f"🎵 کیفیت دانلود ({quality_text})", callback_data="show_quality_menu")],
        [InlineKeyboardButton(text=f"{'✅' if show_artwork else '❌'} 🖼️ نمایش کاور", callback_data="menu_artwork")],
        [InlineKeyboardButton(text=f"{'✅' if auto_download else '❌'} 📥 دانلود خودکار", callback_data="menu_auto_download")],
        [InlineKeyboardButton(text=f"{'✅' if notifications else '❌'} 🔔 دریافت اعلان", callback_data="menu_notifications")]
    ]

def get_quality_keyboard(current_quality):
    from models.schemas import DownloadQuality
    return [
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.HIGH else ''}🎵 ۳۲۰ kbps", callback_data="set_quality:320")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.MEDIUM else ''}🎶 ۱۹۲ kbps", callback_data="set_quality:192")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.LOW else ''}🎧 ۱۲۸ kbps", callback_data="set_quality:128")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_quality == DownloadQuality.ASK else ''}❓ هر بار بپرس", callback_data="set_quality:ask")],
        [InlineKeyboardButton(text="🔙 بازگشت به تنظیمات", callback_data="back_to_settings")]
    ]

def get_confirmation_keyboard(setting_type, new_value):
    return [
        [
            InlineKeyboardButton(text="✅ بله، تغییر کن", callback_data=f"confirm_{setting_type}:{int(new_value)}"),
            InlineKeyboardButton(text="❌ خیر، انصراف", callback_data="back_to_settings")
        ]
    ]
