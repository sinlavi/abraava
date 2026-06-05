from balethon.objects import InlineKeyboard, Message
from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button
import logging

logger = logging.getLogger("ABRAAVA:MESSAGES")

def _prepare_markup(reply_markup, no_close):
    if reply_markup is None: reply_markup = []
    if isinstance(reply_markup, list):
        # Flattened check for close button
        has_close = False
        for row in reply_markup:
            if isinstance(row, list):
                for btn in row:
                    if getattr(btn, 'callback_data', '') == 'close':
                        has_close = True
                        break
        if not no_close and not has_close:
            reply_markup.append([create_info_channel_button()])
            reply_markup.append([create_close_button()])
        return InlineKeyboard(*reply_markup)
    return reply_markup

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False):
    markup = _prepare_markup(reply_markup, no_close)
    return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)

async def edit_message(message, text, reply_markup=None, no_close=False):
    markup = _prepare_markup(reply_markup, no_close)
    try:
        if hasattr(message, 'photo') and message.photo:
            return await message.edit_caption(caption=f"{text}{FOOTER}", reply_markup=markup)
        return await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
    except Exception as e:
        logger.warning(f"Failed to edit message {message.id}, sending new message instead: {e}")
        # Fallback: send new message if edit fails (e.g. message deleted)
        return await send_message(message.client, message.chat.id, text, reply_markup=markup, no_close=no_close)

async def reply_message(message: Message, text: str, reply_markup=None):
    markup = _prepare_markup(reply_markup, False)
    return await message.reply(text=f"{text}{FOOTER}", reply_markup=markup)
