from core.config import FOOTER
from bot.keyboards import create_close_button, create_info_channel_button, create_cancel_button, create_cancel_operation_button
import logging
import copy
import asyncio

logger = logging.getLogger("ABRAAVA:MESSAGES")

def _prepare_markup(reply_markup, no_close, show_info=False, task_id=None, show_cancel=False):
    if reply_markup is None: reply_markup = []
    if isinstance(reply_markup, list):
        # Create a deep copy to avoid modifying the original list passed by reference
        markup = copy.deepcopy(reply_markup)

        # Flatten and check for close button in all nested lists
        has_close = False
        for row in markup:
            if isinstance(row, list):
                for btn in row:
                    if isinstance(btn, dict) and btn.get('callback_data', '').startswith('close'):
                        has_close = True
                        break
            if has_close: break

        if not no_close and not has_close:
            if task_id:
                markup.append([create_cancel_button(task_id)])
            elif show_cancel:
                markup.append([create_cancel_operation_button()])
            elif show_info:
                markup.append([create_info_channel_button()])

            # Final check just in case something was added but not 'close'
            has_close_now = False
            for row in markup:
                if isinstance(row, list):
                    for btn in row:
                        if isinstance(btn, dict) and btn.get('callback_data', '').startswith('close'):
                            has_close_now = True
                            break
                if has_close_now: break

            if not has_close_now:
                markup.append([create_close_button()])

        return markup
    return reply_markup

async def safe_delete(message, attempt=1):
    if not message: return
    try:
        await message.delete()
    except Exception as e:
        err = str(e).lower()
        if "message not found" in err: return
        if ("rate limit" in err or "too many" in err) and attempt < 3:
            await asyncio.sleep(0.5 * attempt)
            return await safe_delete(message, attempt + 1)
        logger.debug(f"Safe delete failed: {e}")

async def send_message(bot, chat_id, text, reply_markup=None, no_close=False, show_info=False, task_id=None, show_cancel=False, reply_to_message_id=None):
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)
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
    chat_id = message.chat.id
    markup = _prepare_markup(reply_markup, no_close, show_info, task_id, show_cancel)

    try:
        return await message.edit(text=f"{text}{FOOTER}", reply_markup=markup)
    except Exception as e:
        err_msg = str(e).lower()

        if "message is not modified" in err_msg:
            return message

        if "message not found" in err_msg:
            return await send_message(message.client_wrapper if hasattr(message, 'client_wrapper') else message.client, chat_id, text, reply_markup=markup, no_close=no_close, show_info=show_info, task_id=task_id)

        max_attempts = 10 if force_edit else 3
        if ("rate limit" in err_msg or "too many" in err_msg) and attempt < max_attempts:
            await asyncio.sleep(0.5 * attempt)
            return await edit_message(message, text, reply_markup, no_close, show_info, task_id, force_edit, show_cancel, attempt + 1)

        if force_edit:
            logger.error(f"Force edit failed after {attempt} attempts: {e}")
            return message

        logger.warning(f"Failed to edit (attempt {attempt}), sending new: {e}")
        try:
            await safe_delete(message)
        except Exception:
            pass

        return await send_message(message.client_wrapper if hasattr(message, 'client_wrapper') else message.client, chat_id, text, reply_markup=markup, no_close=no_close, show_info=show_info, task_id=task_id)

async def reply_message(message, text: str, reply_markup=None, show_info=False):
    markup = _prepare_markup(reply_markup, False, show_info)
    await message.client_wrapper.send_chat_action(message.chat.id, "typing")
    return await message.reply(text=f"{text}{FOOTER}", reply_markup=markup)
