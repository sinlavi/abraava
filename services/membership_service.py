from typing import Dict, Any, List
from core.logger import logger
from services.api_client import APIClient

async def check_channel_membership(bot, user_id: int, channel_id: str) -> bool:
    try:
        if hasattr(bot, "get_chat_member"):
            chat_member = await bot.get_chat_member(channel_id, user_id)
            if chat_member and chat_member.status in ['member', 'administrator', 'creator']:
                return True
        else:
            from core.bot_client import BotClient
            if isinstance(bot, BotClient):
                # We need a proper get_chat_member in our BotClient abstraction if we really want to abstract it
                # For now let's try direct Telethon call if it's Telethon
                from telethon.tl.functions.channels import GetParticipantRequest
                from telethon.tl.types import ChannelParticipantMember, ChannelParticipantAdmin, ChannelParticipantCreator
                try:
                    participant = await bot.client(GetParticipantRequest(channel_id, user_id))
                    if isinstance(participant.participant, (ChannelParticipantMember, ChannelParticipantAdmin, ChannelParticipantCreator)):
                        return True
                except:
                    return False
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
