from core.config import INFO_CHANNEL_ID, FOOTER
from services.api_client import APIClient
import asyncio
import logging

logger = logging.getLogger("ABRAAVA:BROADCAST")

_broadcast_cache = {"channels": None, "users": None, "expire": 0}

async def process_broadcast_message(bot, message, api_client):
    chat_type = getattr(message.chat, "type", None)
    if chat_type != "channel": return

    chat_id = str(message.chat.id)

    # Logic for Info Channel processing
    is_info_channel = chat_id == str(INFO_CHANNEL_ID)
    if is_info_channel:
        text = getattr(message, "content", None) or getattr(message, "text", "") or getattr(message, "caption", "") or ""
        # If ID/Tag is missing, edit and add it
        if "@abraava" not in text or "@abraava_bot" not in text:
            try:
                new_text = text
                if "@abraava" not in new_text: new_text += "\n@abraava"
                if "@abraava_bot" not in new_text: new_text += "\n@abraava_bot"

                if hasattr(message, "edit"):
                    await message.edit(text=new_text)
                else:
                    from core.bot_client import get_bot_client
                    client = get_bot_client()
                    await client.edit_message(message.chat.id, message.id, new_text)
            except Exception as e:
                logger.error(f"Failed to edit info channel message: {e}")

    now = asyncio.get_event_loop().time()
    if _broadcast_cache["channels"] and _broadcast_cache["expire"] > now:
        broadcast_channels = _broadcast_cache["channels"]
    else:
        result = await api_client.get_broadcast_channels()
        if not result.get('success'): return
        broadcast_channels = result.get('data', [])
        _broadcast_cache["channels"] = broadcast_channels
        _broadcast_cache["expire"] = now + 300 # 5 min cache

    channel_config = next((c for c in broadcast_channels if str(c.get('channel_id')) == chat_id), None)
    if not channel_config: return

    message_text = getattr(message, "content", None) or getattr(message, "text", "") or getattr(message, "caption", "") or ""
    keywords = channel_config.get('keywords', '#اطلاع_رسانی #ابرآوا')
    keyword_list = [kw.strip() for kw in keywords.split() if kw.strip()]

    if not any(keyword in message_text for keyword in keyword_list): return

    if _broadcast_cache["users"] and _broadcast_cache["expire"] > now:
        users = _broadcast_cache["users"]
    else:
        users_result = await api_client.get_active_users()
        if not users_result.get('success'): return
        users = users_result.get('data', [])
        _broadcast_cache["users"] = users

    successful, failed = 0, 0

    logger.info(f"Starting broadcast from {chat_id} to {len(users)} users. Keywords: {keyword_list}")

    semaphore = asyncio.Semaphore(20)

    async def forward_to_user(user):
        nonlocal successful, failed
        uid = user.get('user_id') or user.get('id')
        if not uid: return
        async with semaphore:
            try:
                if hasattr(bot, "forward_message"):
                    await bot.forward_message(chat_id=uid, message_id=message.id, from_chat_id=message.chat.id)
                else:
                    from core.bot_client import get_bot_client
                    client = get_bot_client()
                    # Telethon forward
                    await client.client.forward_messages(uid, message)
                successful += 1
            except Exception as e:
                logger.debug(f"Failed to forward broadcast to {uid}: {e}")
                failed += 1

    tasks = [forward_to_user(user) for user in users]
    await asyncio.gather(*tasks)

    logger.info(f"Broadcast complete: {successful} success, {failed} failed.")
    await api_client.log_broadcast(str(message.id), chat_id, message_text[:500], len(users), successful, failed)
