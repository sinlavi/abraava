from balethon.objects import InlineKeyboard, Message, InlineKeyboardButton
from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button, create_cancel_button
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

async def safe_delete(message):
    if not message: return
    try:
        await message.delete()
    except Exception as e:
        if "message not found" not in str(e).lower():
            logger.debug(f"Safe delete failed: {e}")

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False, show_info=False, task_id=None, show_cancel=False):
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)
    return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)

async def edit_message(message, text, reply_markup=None, no_close=False, show_info=False, task_id=None, force_edit=False, show_cancel=False):
    if not message: return None
    chat_id = message.chat.id
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)

    try:
        if hasattr(message, 'photo') and message.photo:
            return await message.edit_caption(caption=f"{text}{FOOTER}", reply_markup=markup)
        else:
            return await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
    except Exception as e:
        err_msg = str(e).lower()
        if "message not found" not in err_msg:
            logger.warning(f"Failed to edit, sending new: {e}")
            await safe_delete(message)
        return await send_message(message.client, chat_id, text, reply_markup=markup, no_close=no_close, show_info=show_info, task_id=task_id)

async def reply_message(message: Message, text: str, reply_markup=None, show_info=False):
    markup = _prepare_markup(reply_markup, False, show_info)
    return await message.reply(text=f"{text}{FOOTER}", reply_markup=markup)
