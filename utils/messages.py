from balethon.objects import InlineKeyboard
from core.config import FOOTER
from bot.keyboards import create_close_button

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False):
    if reply_markup is None:
        reply_markup = []

    if not no_close:
        # Check if it's already an InlineKeyboard or a list of lists
        if isinstance(reply_markup, InlineKeyboard):
            # InlineKeyboard doesn't easily support appending rows after creation in some versions
            # but we can pass its rows to a new one
            rows = list(reply_markup.rows)
            rows.append([create_close_button()])
            reply_markup = InlineKeyboard(*rows)
        elif isinstance(reply_markup, list):
            reply_markup.append([create_close_button()])
            reply_markup = InlineKeyboard(*reply_markup)

    return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=reply_markup)

async def edit_message(message, text, reply_markup=None, no_close=False):
    if reply_markup is None:
        reply_markup = []

    if not no_close:
        if isinstance(reply_markup, InlineKeyboard):
            rows = list(reply_markup.rows)
            rows.append([create_close_button()])
            reply_markup = InlineKeyboard(*rows)
        elif isinstance(reply_markup, list):
            reply_markup.append([create_close_button()])
            reply_markup = InlineKeyboard(*reply_markup)

    return await message.edit(text=f"{text}{FOOTER}", reply_markup=reply_markup)
