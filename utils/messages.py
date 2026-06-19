from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button, create_cancel_button
import logging
import copy
import asyncio

logger = logging.getLogger("ABRAAVA:MESSAGES")

def _prepare_markup(bot, reply_markup, no_close, show_info=False, task_id=None, show_cancel=False):
    if reply_markup is None: reply_markup = []
    if isinstance(reply_markup, list):
        markup = copy.deepcopy(reply_markup)
        has_close = any(btn.get('callback_data', '').startswith('close') for row in markup if isinstance(row, list) for btn in row)
        if not no_close and not has_close:
            if task_id: markup.append([create_cancel_button(task_id)])
            elif show_cancel: markup.append([{"text": "⏹️ لغو عملیات", "callback_data": "close"}])
            elif show_info: markup.append([create_info_channel_button()])
            if not any(btn.get('callback_data', '').startswith('close') for row in markup if isinstance(row, list) for btn in row):
                markup.append([create_close_button()])
        return bot.build_markup(markup)
    return reply_markup

async def safe_delete(message, attempt=1):
    if not message: return
    try: await message.delete()
    except Exception as e:
        err = str(e).lower()
        if "not found" in err: return
        if ("rate limit" in err or "too many" in err) and attempt < 3:
            await asyncio.sleep(0.5 * attempt)
            return await safe_delete(message, attempt + 1)

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False, show_info=False, task_id=None, show_cancel=False, reply_to_message_id=None):
    markup = _prepare_markup(bot, reply_markup, no_close, show_info, task_id, show_cancel)
    try:
        await bot.send_chat_action(chat_id, "typing")
        return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        if "too many" in str(e).lower():
            await asyncio.sleep(1)
            return await bot.send_message(chat_id, text=f"{text}{FOOTER}", reply_markup=markup)
        raise

async def edit_message(message, text, reply_markup=None, no_close=False, show_info=False, task_id=None, force_edit=False, show_cancel=False, attempt=1):
    if not message: return None
    bot = getattr(message, '_client', None)
    if not bot: return None
    markup = _prepare_markup(bot, reply_markup, no_close, show_info, task_id, show_cancel)
    try: return await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
    except Exception as e:
        err_msg = str(e).lower()
        if "is not modified" in err_msg: return message
        if "not found" in err_msg: return await send_message(bot, message.chat_id, text, reply_markup=reply_markup, no_close=no_close, show_info=show_info, task_id=task_id)
        if ("rate limit" in err_msg or "too many" in err_msg) and attempt < (10 if force_edit else 3):
            await asyncio.sleep(0.5 * attempt)
            return await edit_message(message, text, reply_markup, no_close, show_info, task_id, force_edit, show_cancel, attempt + 1)
        return await send_message(bot, message.chat_id, text, reply_markup=reply_markup, no_close=no_close, show_info=show_info, task_id=task_id)

async def reply_message(message, text: str, reply_markup=None, show_info=False):
    bot = getattr(message, '_client', None)
    markup = _prepare_markup(bot, reply_markup, False, show_info)
    await bot.send_chat_action(message.chat_id, "typing")
    return await message.reply(text=f"{text}{FOOTER}", reply_markup=markup)
