from balethon import Client
from balethon.objects import Message
from core.config import INFO_CHANNEL_ID, FOOTER
from services.api_client import APIClient

async def process_broadcast_message(bot: Client, message: Message, api_client: APIClient):
    if message.chat.type != "channel": return

    chat_id = str(message.chat.id)

    # Logic for Info Channel processing
    if chat_id == str(INFO_CHANNEL_ID):
        text = message.content or message.caption or ""
        # If ID/Tag is missing, edit and add it
        if "@abraava" not in text or "@abraava_bot" not in text:
            try:
                # Ensure it has exactly what's needed
                new_text = text
                if "@abraava_bot" not in new_text: new_text += "\n@abraava_bot"
                if "@abraava" not in new_text: new_text += "\n@abraava"

                if message.content: await message.edit(text=new_text)
                elif message.caption: await message.edit_caption(caption=new_text)
            except: pass

    result = await api_client.get_broadcast_channels()
    if not result.get('success'): return

    broadcast_channels = result.get('data', [])
    channel_config = next((c for c in broadcast_channels if str(c.get('channel_id')) == chat_id), None)
    if not channel_config: return

    message_text = message.content or message.caption or ""
    keywords = channel_config.get('keywords', '#اطلاع_رسانی #ابرآوا')
    keyword_list = [kw.strip() for kw in keywords.split() if kw.strip()]

    if not any(keyword in message_text for keyword in keyword_list): return

    users_result = await api_client.get_active_users()
    if not users_result.get('success'): return

    users = users_result.get('data', [])
    successful, failed = 0, 0

    for user in users:
        try:
            uid = user.get('id')
            if uid:
                await bot.forward_message(chat_id=uid, message_id=message.id, from_chat_id=message.chat.id)
                successful += 1
                await asyncio.sleep(0.05)
        except Exception: failed += 1

    await api_client.log_broadcast(str(message.id), chat_id, message_text[:500], len(users), successful, failed)
