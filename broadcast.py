import asyncio

from config import logger, INFO_CHANNEL_ID
from db.utils import get_all_users

broadcast_queue = asyncio.Queue()


async def handle_channel_post(message):
    content = message.content
    should_broadcast = "#تبلیغ" in content or "#اطلاع_رسانی" in content

    if should_broadcast:
        logger.info(f"Broadcasting message from channel: {content[:100]}...")
        users = await get_all_users()
        if users:
            await broadcast_queue.put({"users": users, "message": message})
            logger.info(f"Broadcast queued for {len(users)} users")


async def broadcast_worker():
    logger.info("Broadcast worker started")
    while True:
        try:
            message_data = await broadcast_queue.get()
            users = message_data["users"]
            message = message_data["message"]
            success_count = 0
            fail_count = 0

            for user_id in users:
                try:
                    await bot.forward_message(
                        chat_id=user_id,
                        from_chat_id=int(INFO_CHANNEL_ID),
                        message_id=message.id
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    fail_count += 1

            logger.info(f"Broadcast completed: {success_count} success, {fail_count} failed")
            broadcast_queue.task_done()
        except Exception as e:
            logger.error(f"Broadcast worker error: {e}")
            await asyncio.sleep(5)
