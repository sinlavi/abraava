from balethon.objects import InlineKeyboard, Message
from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button, create_cancel_button
from services.last_message_tracker import last_message_tracker
import logging

logger = logging.getLogger("ABRAAVA:MESSAGES")

def _prepare_markup(reply_markup, no_close, show_info=False, task_id=None):
    if reply_markup is None: reply_markup = []
    if isinstance(reply_markup, list):
        has_close = False
        for row in reply_markup:
            if isinstance(row, list):
                for btn in row:
                    if getattr(btn, 'callback_data', '') == 'close':
                        has_close = True
                        break
        if not no_close and not has_close:
            if task_id:
                reply_markup.append([create_cancel_button(task_id)])
            elif show_info:
                reply_markup.append([create_info_channel_button()])

            if not any(any(getattr(btn, 'callback_data', '') == 'close' for btn in row) for row in reply_markup if isinstance(row, list)):
                reply_markup.append([create_close_button()])
        return InlineKeyboard(*reply_markup)
    return reply_markup

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False, show_info=False, task_id=None):
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id)
    msg = await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)
    if msg: last_message_tracker.set_last(chat_id, msg.id)
    return msg

async def edit_message(message, text, reply_markup=None, no_close=False, show_info=False, task_id=None):
    chat_id = message.chat.id
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id)

    # If it's a photo message and we want to edit it, Balethon sometimes has issues if it's not the last message
    # or if we try to edit text into a photo message without edit_caption.
    # The current logic handles edit_caption correctly if hasattr(message, 'photo').

    if not last_message_tracker.is_recent(chat_id, message.id):
        # Only delete and send new if it's NOT among the recent messages.
        # This prevents the bot from "flickering" if it's still near the end of the chat.
        try: await message.delete()
        except: pass
        return await send_message(message.client, chat_id, text, reply_markup=markup, no_close=no_close, show_info=show_info, task_id=task_id)

    try:
        if hasattr(message, 'photo') and message.photo:
            msg = await message.edit_caption(caption=f"{text}{FOOTER}", reply_markup=markup)
        else:
            msg = await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
        if msg: last_message_tracker.set_last(chat_id, msg.id)
        return msg
    except Exception as e:
        logger.warning(f"Failed to edit, sending new: {e}")
        return await send_message(message.client, chat_id, text, reply_markup=markup, no_close=no_close, show_info=show_info, task_id=task_id)

async def reply_message(message: Message, text: str, reply_markup=None, show_info=False):
    markup = _prepare_markup(reply_markup, False, show_info)
    msg = await message.reply(text=f"{text}{FOOTER}", reply_markup=markup)
    if msg: last_message_tracker.set_last(message.chat.id, msg.id)
    return msg
