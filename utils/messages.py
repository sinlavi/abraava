from balethon.objects import InlineKeyboard, Message, InlineKeyboardButton
from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button, create_cancel_button
from services.last_message_tracker import last_message_tracker
import logging
import copy

logger = logging.getLogger("ABRAAVA:MESSAGES")

def _prepare_markup(reply_markup, no_close, show_info=False, task_id=None, show_cancel=False):
    if reply_markup is None: reply_markup = []
    if isinstance(reply_markup, list):
        # Create a deep copy to avoid modifying the original list passed by reference
        markup = copy.deepcopy(reply_markup)

        # Flatten and check for close button in all nested lists
        has_close = any(
            getattr(btn, 'callback_data', '') == 'close'
            for row in markup
            if isinstance(row, list)
            for btn in row
        )

        if not no_close and not has_close:
            if task_id:
                markup.append([create_cancel_button(task_id)])
            elif show_cancel:
                markup.append([InlineKeyboardButton(text="⏹️ لغو عملیات", callback_data="close")])
            elif show_info:
                markup.append([create_info_channel_button()])

            # Final check just in case something was added but not 'close'
            has_close_now = any(
                getattr(btn, 'callback_data', '') == 'close'
                for row in markup
                if isinstance(row, list)
                for btn in row
            )
            if not has_close_now:
                markup.append([create_close_button()])

        return InlineKeyboard(*markup)
    return reply_markup

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False, show_info=False, task_id=None, show_cancel=False):
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)
    msg = await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)
    if msg: last_message_tracker.set_last(chat_id, msg.id)
    return msg

async def edit_message(message, text, reply_markup=None, no_close=False, show_info=False, task_id=None, force_edit=False, show_cancel=False):
    if not message: return None
    chat_id = message.chat.id
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)

    # If it's a photo message and we want to edit it, Balethon sometimes has issues if it's not the last message
    # or if we try to edit text into a photo message without edit_caption.
    # The current logic handles edit_caption correctly if hasattr(message, 'photo').

    if not force_edit and not last_message_tracker.is_recent(chat_id, message.id):
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
