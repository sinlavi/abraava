from abc import ABC, abstractmethod
from typing import Union, List, Optional
import io
import asyncio
from core.logger import logger

class BotClient(ABC):
    def __init__(self, token: str, proxy: str = None):
        self.token = token
        self.proxy = proxy
        self.user = None

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def send_message(self, chat_id: Union[int, str], text: str, reply_markup=None, reply_to_message_id=None):
        pass

    @abstractmethod
    async def edit_message(self, chat_id: Union[int, str], message_id: int, text: str, reply_markup=None):
        pass

    @abstractmethod
    async def delete_message(self, chat_id: Union[int, str], message_id: int):
        pass

    @abstractmethod
    async def send_audio(self, chat_id: Union[int, str], audio: Union[str, bytes, io.BytesIO], caption: str = None, reply_markup=None, reply_to_message_id=None):
        pass

    @abstractmethod
    async def send_photo(self, chat_id: Union[int, str], photo: Union[str, bytes, io.BytesIO], caption: str = None, reply_markup=None, reply_to_message_id=None):
        pass

    @abstractmethod
    async def send_voice(self, chat_id: Union[int, str], voice: Union[str, bytes, io.BytesIO], caption: str = None, reply_markup=None, reply_to_message_id=None):
        pass

    @abstractmethod
    async def send_chat_action(self, chat_id: Union[int, str], action: str):
        pass

    @abstractmethod
    async def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        pass

    @abstractmethod
    async def forward_message(self, chat_id: Union[int, str], from_chat_id: Union[int, str], message_id: int):
        pass

    @abstractmethod
    async def get_chat(self, chat_id: Union[int, str]):
        pass

    @abstractmethod
    async def get_chat_member(self, chat_id: Union[int, str], user_id: int):
        pass

class BaleClient(BotClient):
    def __init__(self, token: str, proxy: str = None):
        super().__init__(token, proxy)
        from balethon import Client
        self.client = Client(token=token, proxy=proxy)

    async def start(self):
        await self.client.connect()
        self.user = await self.client.get_me()

    async def stop(self):
        await self.client.disconnect()

    def _convert_markup(self, markup):
        if not markup: return None
        if not isinstance(markup, list): return markup # Already converted or object
        from balethon.objects import InlineKeyboard, InlineKeyboardButton
        rows = []
        for row in markup:
            if isinstance(row, list):
                btn_row = []
                for btn in row:
                    if isinstance(btn, dict):
                        if "url" in btn:
                            btn_row.append(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
                        elif "callback_data" in btn:
                            btn_row.append(InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]))
                        elif "web_app" in btn:
                             btn_row.append(InlineKeyboardButton(text=btn["text"], web_app=btn["web_app"]))
                        elif "copy_text" in btn:
                             btn_row.append(InlineKeyboardButton(text=btn["text"], copy_text=btn["copy_text"]))
                    else:
                        btn_row.append(btn)
                rows.append(btn_row)
        return InlineKeyboard(*rows)

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_message(chat_id, text, self._convert_markup(reply_markup), reply_to_message_id)

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        return await self.client.edit_message(chat_id, message_id, text, self._convert_markup(reply_markup))

    async def delete_message(self, chat_id, message_id):
        return await self.client.delete_message(chat_id, message_id)

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_audio(chat_id, audio, caption, reply_markup=self._convert_markup(reply_markup), reply_to_message_id=reply_to_message_id)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_photo(chat_id, photo, caption, reply_markup=self._convert_markup(reply_markup), reply_to_message_id=reply_to_message_id)

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_voice(chat_id, voice, caption, reply_markup=self._convert_markup(reply_markup), reply_to_message_id=reply_to_message_id)

    async def send_chat_action(self, chat_id, action):
        return await self.client.send_chat_action(chat_id, action)

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        return await self.client.answer_callback_query(callback_query_id, text, show_alert)

    async def forward_message(self, chat_id, from_chat_id, message_id):
        return await self.client.forward_message(chat_id, message_id, from_chat_id)

    async def get_chat(self, chat_id):
        return await self.client.get_chat(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        return await self.client.get_chat_member(chat_id, user_id)

class TelegramClient(BotClient):
    def __init__(self, token: str, api_id: int, api_hash: str, proxy: str = None):
        super().__init__(token, proxy)
        from telethon import TelegramClient as TeleClient
        from telethon.network import ConnectionTcpMTProxyRandomized
        proxy_dict = None
        if proxy:
            import socks
            p_type, p_rest = proxy.split("://")
            p_host, p_port = p_rest.split(":")
            proxy_dict = (socks.SOCKS5, p_host, int(p_port))

        self.client = TeleClient("abraava_bot", api_id, api_hash, proxy=proxy_dict)

    async def start(self):
        await self.client.start(bot_token=self.token)
        self.user = await self.client.get_me()

    async def stop(self):
        await self.client.disconnect()

    def _convert_markup(self, markup):
        if not markup: return None
        if not isinstance(markup, list): return markup
        from telethon import Button
        rows = []
        for row in markup:
            if isinstance(row, list):
                btn_row = []
                for btn in row:
                    if isinstance(btn, dict):
                        if "url" in btn:
                            btn_row.append(Button.url(btn["text"], btn["url"]))
                        elif "callback_data" in btn:
                            btn_row.append(Button.inline(btn["text"], btn["callback_data"]))
                        elif "web_app" in btn:
                             # Telethon uses Button.url for web apps too or Button.web_app
                             btn_row.append(Button.url(btn["text"], btn["web_app"]))
                        elif "copy_text" in btn:
                             # Telegram doesn't have direct copy_text button, use callback or just text
                             btn_row.append(Button.inline(btn["text"], f"copy:{btn['copy_text']}"))
                    else:
                        btn_row.append(btn)
                rows.append(btn_row)
        return rows

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_message(chat_id, text, buttons=self._convert_markup(reply_markup), reply_to=reply_to_message_id, parse_mode='md')

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        return await self.client.edit_message(chat_id, message_id, text, buttons=self._convert_markup(reply_markup), parse_mode='md')

    async def delete_message(self, chat_id, message_id):
        return await self.client.delete_messages(chat_id, [message_id])

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_file(chat_id, audio, caption=caption, buttons=self._convert_markup(reply_markup), reply_to=reply_to_message_id, parse_mode='md')

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_file(chat_id, photo, caption=caption, buttons=self._convert_markup(reply_markup), reply_to=reply_to_message_id, parse_mode='md')

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, reply_to_message_id=None):
        return await self.client.send_file(chat_id, voice, caption=caption, buttons=self._convert_markup(reply_markup), reply_to=reply_to_message_id, voice=True, parse_mode='md')

    async def send_chat_action(self, chat_id, action):
        # Translate Bale actions to Telethon
        action_map = {"typing": "typing", "upload_photo": "photo", "record_voice": "record-audio", "upload_voice": "audio"}
        async with self.client.action(chat_id, action_map.get(action, "typing")):
            await asyncio.sleep(0.1)

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        # In Telethon, we usually answer via event.answer()
        # but if we have the ID, we can use the RPC
        from telethon.tl.functions.messages import SetBotCallbackAnswerRequest
        return await self.client(SetBotCallbackAnswerRequest(
            query_id=int(callback_query_id),
            message=text,
            alert=show_alert
        ))

    async def forward_message(self, chat_id, from_chat_id, message_id):
        return await self.client.forward_messages(chat_id, message_id, from_chat_id)

    async def get_chat(self, chat_id):
        return await self.client.get_entity(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        from telethon.tl.functions.channels import GetParticipantRequest
        from telethon.tl.types import ChannelParticipant, ChannelParticipantAdmin, ChannelParticipantCreator
        try:
            p = await self.client(GetParticipantRequest(chat_id, user_id))
            participant = p.participant
            status = 'member'
            if isinstance(participant, ChannelParticipantAdmin): status = 'administrator'
            elif isinstance(participant, ChannelParticipantCreator): status = 'creator'

            # Create a compatibility object
            class Member:
                def __init__(self, status):
                    self.status = status
            return Member(status)
        except:
            return None
