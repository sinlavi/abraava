from balethon.objects import InlineKeyboard, Message
from core.config import FOOTER
from bot.keyboards import create_close_button

def _prepare_markup(reply_markup, no_close):
    if reply_markup is None:
        reply_markup = []

    if isinstance(reply_markup, list):
        # Check if close button already exists in any row
        has_close = any(any(getattr(btn, 'callback_data', '') == 'close' for btn in row) for row in reply_markup if isinstance(row, list))
        if not no_close and not has_close:
            reply_markup.append([create_close_button()])
        return InlineKeyboard(*reply_markup)

    return reply_markup

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False):
    markup = _prepare_markup(reply_markup, no_close)
    return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)

async def edit_message(message, text, reply_markup=None, no_close=False):
    markup = _prepare_markup(reply_markup, no_close)

    # Balethon handles editing differently if it's a photo caption
    if hasattr(message, 'photo') and message.photo:
        return await message.edit_caption(caption=f"{text}{FOOTER}", reply_markup=markup)

    return await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
