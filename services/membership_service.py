from typing import Dict, Any, List
from core.logger import logger

async def check_channel_membership(bot, user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        if member and hasattr(member, 'status'):
            return member.status in ['member', 'administrator', 'creator', 'owner']
        return False
    except Exception as e:
        logger.error(f"Failed to check membership for {user_id} in {channel_id}: {e}")
        return False

async def verify_all_memberships(bot, user_id: int, api_client) -> tuple[bool, List[Dict]]:
    result = await api_client.get_required_channels()
    if not result.get('success'): return True, []
    channels = result.get('data', [])
    missing_channels = []
    for channel in channels:
        if not await check_channel_membership(bot, user_id, channel.get('channel_id')):
            missing_channels.append(channel)
    return len(missing_channels) == 0, missing_channels
