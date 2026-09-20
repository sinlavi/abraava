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

def create_retry_button(callback_data: str, user_id: int = None, button_text: str = "🔄 تلاش مجدد") -> InlineKeyboardButton:
    cb = callback_data if callback_data.startswith("retry:") else f"retry:{callback_data}"
    if user_id: cb += f":u{user_id}"
    return InlineKeyboardButton(text=button_text, callback_data=cb)

def create_pagination_row(callback_prefix: str, current_page: int, total_pages: int, user_id: int = None):
    if total_pages <= 1: return []
    buttons = []

    suffix = f":u{user_id}" if user_id else ""

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

def get_search_choice_keyboard(user_id: int, query_id: str):
    suffix = f":u{user_id}" if user_id else ""
    return InlineKeyboard(
        [InlineKeyboardButton(text="🔍 جستجو در مینی‌اپ", web_app="https://mm.3rah.ir/ui")],
        [InlineKeyboardButton(text="💬 جستجو در چت", callback_data=f"search_chat:{query_id}{suffix}")],
        [create_close_button(user_id)]
    )

def get_social_buttons_row(entity_type: str, entity_id: str, is_liked: bool = False, like_count: int = 0, is_in_library: bool = False, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    like_icon = "❤️" if is_liked else "🤍"
    like_text = f"{like_icon} {like_count}" if like_count > 0 else f"{like_icon} پسندیدن"
    like_cb = f"like_toggle:{entity_type}:{entity_id}{suffix}"

    lib_icon = "🗑️" if is_in_library else "📌"
    lib_text = f"{lib_icon} کتابخانه"
    lib_cb = f"lib_toggle:{entity_type}:{entity_id}{suffix}"

    comment_text = "💬 نظرات"
    comment_cb = f"comments:{entity_type}:{entity_id}{suffix}"

    buttons = [
        InlineKeyboardButton(text=like_text, callback_data=like_cb),
        InlineKeyboardButton(text=lib_text, callback_data=lib_cb),
        InlineKeyboardButton(text=comment_text, callback_data=comment_cb)
    ]
    if entity_type == 'track':
        pl_btn = InlineKeyboardButton(text="➕ لیست پخش", callback_data=f"add_to_pl:{entity_id}{suffix}")
        buttons.append(pl_btn)
    return buttons

def get_my_hub_keyboard(user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    return InlineKeyboard(
        [InlineKeyboardButton(text="📌 کتابخانه من", callback_data=f"my_lib:all{suffix}"),
         InlineKeyboardButton(text="🎶 لیست‌های پخش من", callback_data=f"my_playlists{suffix}")],
        [InlineKeyboardButton(text="🎤 هنرمندان دنبال شده", callback_data=f"my_artists{suffix}"),
         InlineKeyboardButton(text="📜 تاریخچه پخش", callback_data=f"my_history{suffix}")],
        [InlineKeyboardButton(text="🔥 محبوب‌ترین‌ها", callback_data=f"popular_tracks{suffix}"),
         InlineKeyboardButton(text="🆕 تازه اضافه شده", callback_data=f"fresh_tracks{suffix}")],
        [create_close_button(user_id)]
    )

def get_artist_social_row(artist_id: str, is_following: bool = False, user_id: int = None):
    suffix = f":u{user_id}" if user_id else ""
    follow_text = "➖ لغو دنبال کردن" if is_following else "➕ دنبال کردن هنرمند"
    follow_cb = f"follow_artist_toggle:{artist_id}{suffix}"
    tracks_cb = f"artist_tracks:{artist_id}:1{suffix}"

    return [
        InlineKeyboardButton(text=follow_text, callback_data=follow_cb),
        InlineKeyboardButton(text="🎵 لیست تمام آهنگ‌ها", callback_data=tracks_cb)
    ]
