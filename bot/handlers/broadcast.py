from core.platform import MessageAdapter
from utils.messages import send_message
import logging
import asyncio

logger = logging.getLogger("ABRAAVA:BROADCAST")

async def process_broadcast_message(bot, message: MessageAdapter, api_client):
    """Handles messages from the info channel for broadcasting to users."""
    text = message.text
    if not text: return

    # Check for keywords
    from core.config import BROADCAST_KEYWORDS
    if not any(kw in text for kw in BROADCAST_KEYWORDS):
        return

    logger.info(f"Broadcasting message: {text[:50]}...")

    # In a real bot, we'd get all user IDs from DB
    result = await api_client.get_all_users()
    if not result.get('success'):
        logger.error(f"Failed to get users for broadcast: {result.get('error')}")
        return

    users = result.get('data', [])
    total_users = len(users)
    logger.info(f"Sending broadcast to {total_users} users")

    success_count = 0
    fail_count = 0

    # We use a semaphore to control concurrency
    semaphore = asyncio.Semaphore(50)

    async def send_to_user(user_id):
        nonlocal success_count, fail_count
        async with semaphore:
            try:
                await send_message(bot, user_id, text)
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.debug(f"Broadcast failed for {user_id}: {e}")

    tasks = [send_to_user(user_id) for user_id in users]
    await asyncio.gather(*tasks)

    logger.info(f"Broadcast completed. Success: {success_count}, Failed: {fail_count}")
