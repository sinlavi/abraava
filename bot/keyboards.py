from core.config import FOOTER, INFO_CHANNEL_USERNAME, PLATFORM

def create_close_button(user_id: int = None) -> dict:
    cb = f"close:u{user_id}" if user_id else "close"
    return {"text": "❌ بستن", "callback_data": cb}

def create_cancel_button(task_id: str, user_id: int = None) -> dict:
    cb = f"cancel_task:{task_id}"
    if user_id: cb += f":u{user_id}"
    return {"text": "⏹️ توقف", "callback_data": cb}

def create_info_channel_button() -> dict:
    link = f"https://t.me/{INFO_CHANNEL_USERNAME.lstrip('@')}" if PLATFORM == "telegram" else f"https://ble.ir/{INFO_CHANNEL_USERNAME.lstrip('@')}"
    return {"text": "📢 کانال اطلاع‌رسانی", "url": link}

def create_retry_button(callback_data: str, user_id: int = None, button_text: str = "🔄 تلاش مجدد") -> dict:
    cb = callback_data if callback_data.startswith("retry:") else f"retry:{callback_data}"
    if user_id: cb += f":u{user_id}"
    return {"text": button_text, "callback_data": cb}

def create_pagination_row(callback_prefix: str, current_page: int, total_pages: int, user_id: int = None):
    if total_pages <= 1: return []
    buttons = []

    suffix = f":u{user_id}" if user_id else ""

    # Following RTL flow: [First ⏭️] [Prev ▶️] [Page] [Next ◀️] [Last ⏮️]
    if current_page > 1:
        buttons.append({"text": "⏭️", "callback_data": f"{callback_prefix}:1{suffix}"})
        buttons.append({"text": "▶️", "callback_data": f"{callback_prefix}:{current_page - 1}{suffix}"})

    buttons.append({"text": f"{current_page} از {total_pages}", "callback_data": "ignore"})

    if current_page < total_pages:
        buttons.append({"text": "◀️", "callback_data": f"{callback_prefix}:{current_page + 1}{suffix}"})
        buttons.append({"text": "⏮️", "callback_data": f"{callback_prefix}:{total_pages}{suffix}"})

    return buttons

def get_settings_keyboard(quick_mode, quality_text, show_artwork, auto_download, notifications, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    return [
        [{"text": f"{'✅' if quick_mode else '❌'} ⚡ حالت سریع", "callback_data": f"menu_quick_mode{suffix}"}],
        [{"text": f"🎵 کیفیت دانلود ({quality_text})", "callback_data": f"show_quality_menu{suffix}"}],
        [{"text": f"{'✅' if show_artwork else '❌'} 🖼️ نمایش کاور", "callback_data": f"menu_artwork{suffix}"}],
        [{"text": f"{'✅' if auto_download else '❌'} 📥 دانلود خودکار", "callback_data": f"menu_auto_download{suffix}"}],
        [{"text": f"{'✅' if notifications else '❌'} 🔔 دریافت اعلان", "callback_data": f"menu_notifications{suffix}"}]
    ]

def get_quality_keyboard(current_quality, user_id: int = None):
    from models.schemas import DownloadQuality
    suffix = f":u{user_id}" if user_id else ""
    return [
        [{"text": f"{'✅ ' if current_quality == DownloadQuality.HIGH else ''}🎵 ۳۲۰ kbps", "callback_data": f"set_quality:320{suffix}"}],
        [{"text": f"{'✅ ' if current_quality == DownloadQuality.MEDIUM else ''}🎶 ۱۹۲ kbps", "callback_data": f"set_quality:192{suffix}"}],
        [{"text": f"{'✅ ' if current_quality == DownloadQuality.LOW else ''}🎧 ۱۲۸ kbps", "callback_data": f"set_quality:128{suffix}"}],
        [{"text": f"{'✅ ' if current_quality == DownloadQuality.ASK else ''}❓ هر بار بپرس", "callback_data": f"set_quality:ask{suffix}"}],
        [{"text": "🔙 بازگشت به تنظیمات", "callback_data": f"back_to_settings{suffix}"}]
    ]

def get_confirmation_keyboard(setting_type, new_value, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    return [
        [
            {"text": "✅ بله، تغییر کن", "callback_data": f"confirm_{setting_type}:{int(new_value)}{suffix}"},
            {"text": "❌ خیر، انصراف", "callback_data": f"back_to_settings{suffix}"}
        ]
    ]

def create_cancel_operation_button() -> dict:
    return {"text": "⏹️ لغو عملیات", "callback_data": "close"}
