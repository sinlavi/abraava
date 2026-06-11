from typing import Dict, Any, List
from core.logger import logger
from services.api_client import APIClient
async def check_channel_membership(bot, user_id: int, channel_id: str) -> bool:
    try:
        chat_member = await bot.get_chat_member(channel_id, user_id)
        if not chat_member: return False

        # Cross platform status check
        status = getattr(chat_member, 'status', None)
        if status in ['member', 'administrator', 'creator']:
            return True

        # Telethon Participant check
        from core.config import PLATFORM
        if PLATFORM == "telegram":
            from telethon.tl.types import ChannelParticipant, ChannelParticipantAdmin, ChannelParticipantCreator
            if isinstance(chat_member, (ChannelParticipant, ChannelParticipantAdmin, ChannelParticipantCreator)):
                return True

        return False
    except Exception as e:
        logger.error(f"Failed to check membership: {e}")
        return False

async def verify_all_memberships(bot, user_id: int, api_client: APIClient) -> tuple[bool, List[Dict]]:
    result = await api_client.get_required_channels()
    if not result.get('success'):
        return True, []

    channels = result.get('data', [])
    missing_channels = []

    for channel in channels:
        channel_id = channel.get('channel_id')
        if not await check_channel_membership(bot, user_id, channel_id):
            missing_channels.append(channel)

    return len(missing_channels) == 0, missing_channels
