import os
from enum import Enum
from typing import Union, List, Optional
import asyncio
from core.logger import logger

class Platform(Enum):
    BALE = "bale"
    TELEGRAM = "telegram"

# Global platform state
CURRENT_PLATFORM = Platform(os.getenv("PLATFORM", "bale").lower())

# For Telegram
try:
    from telethon import TelegramClient, events, Button
except ImportError:
    TelegramClient = events = Button = None

# For Bale
try:
    from balethon import Client as BaleClient
    from balethon.objects import Message as BaleMessage, CallbackQuery as BaleCallbackQuery
    from balethon.objects import InlineKeyboard as BaleInlineKeyboard, InlineKeyboardButton as BaleInlineKeyboardButton
except ImportError:
    BaleClient = BaleMessage = BaleCallbackQuery = BaleInlineKeyboard = BaleInlineKeyboardButton = None

class MessageAdapter:
    def __init__(self, message, client_adapter):
        self.raw = message
        self.client = client_adapter

        if CURRENT_PLATFORM == Platform.BALE:
            self.id = message.id
            self.chat_id = message.chat.id
            self.user_id = message.author.id if message.author else None
            self.text = message.content or ""
            self.author_is_bot = message.author.is_bot if message.author else False
            self.chat_type = message.chat.type
        else:
            self.id = message.id
            self.chat_id = message.chat_id
            self.user_id = message.sender_id
            self.text = message.text or ""
            # Telethon sender might be None in some cases, or a Peer object
            self.author_is_bot = getattr(message.sender, 'bot', False) if message.sender else False
            self.chat_type = "private" if message.is_private else ("group" if message.is_group else "channel")

    async def edit(self, text, reply_markup=None):
        if CURRENT_PLATFORM == Platform.BALE:
            return await self.raw.edit(text=text, reply_markup=reply_markup)
        else:
            return await self.client.raw.edit_message(self.chat_id, self.id, text, buttons=reply_markup, link_preview=False)

    async def reply(self, text, reply_markup=None):
        if CURRENT_PLATFORM == Platform.BALE:
            return await self.raw.reply(text=text, reply_markup=reply_markup)
        else:
            return await self.raw.reply(text, buttons=reply_markup, link_preview=False)

    async def delete(self):
        if CURRENT_PLATFORM == Platform.BALE:
            return await self.raw.delete()
        else:
            return await self.client.raw.delete_messages(self.chat_id, [self.id])

class CallbackQueryAdapter:
    def __init__(self, query, client_adapter):
        self.raw = query
        self.client = client_adapter

        if CURRENT_PLATFORM == Platform.BALE:
            self.id = query.id
            self.data = query.data
            self.message = MessageAdapter(query.message, client_adapter) if query.message else None
            self.user_id = query.author.id
        else:
            self.id = str(query.query_id)
            self.data = query.data.decode() if isinstance(query.data, bytes) else query.data
            self.message = MessageAdapter(query.message, client_adapter) if query.message else None
            self.user_id = query.sender_id

    async def answer(self, text=None, show_alert=False):
        if CURRENT_PLATFORM == Platform.BALE:
            return await self.client.raw.answer_callback_query(self.id, text, show_alert)
        else:
            return await self.raw.answer(message=text, alert=show_alert)

class ClientAdapter:
    def __init__(self, token, api_id=None, api_hash=None):
        self.platform = CURRENT_PLATFORM
        self.token = token
        if self.platform == Platform.BALE:
            self.raw = BaleClient(token)
        else:
            self.raw = TelegramClient("abraava_tg", api_id, api_hash)

    async def start(self):
        if self.platform == Platform.BALE:
            # Balethon start is handled by run() or manual connection
            pass
        else:
            await self.raw.start(bot_token=self.token)
            me = await self.raw.get_me()
            self.username = me.username
            logger.info(f"Telegram Bot started as @{self.username}")

    def on_message(self):
        def decorator(f):
            if self.platform == Platform.BALE:
                @self.raw.on_message()
                async def wrapper(message):
                    await f(MessageAdapter(message, self))
            else:
                @self.raw.on(events.NewMessage)
                async def wrapper(event):
                    if event.message:
                        await f(MessageAdapter(event.message, self))
            return f
        return decorator

    def on_callback_query(self):
        def decorator(f):
            if self.platform == Platform.BALE:
                @self.raw.on_callback_query()
                async def wrapper(query):
                    await f(CallbackQueryAdapter(query, self))
            else:
                @self.raw.on(events.CallbackQuery)
                async def wrapper(event):
                    await f(CallbackQueryAdapter(event, self))
            return f
        return decorator

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.platform == Platform.BALE:
            return MessageAdapter(await self.raw.send_message(chat_id, text, reply_markup=reply_markup), self)
        else:
            return MessageAdapter(await self.raw.send_message(chat_id, text, buttons=reply_markup, link_preview=False), self)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        if self.platform == Platform.BALE:
            return MessageAdapter(await self.raw.send_photo(chat_id, photo, caption, reply_markup=reply_markup), self)
        else:
            return MessageAdapter(await self.raw.send_file(chat_id, photo, caption=caption, buttons=reply_markup), self)

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None):
        if self.platform == Platform.BALE:
            return MessageAdapter(await self.raw.send_audio(chat_id, audio, caption=caption, reply_markup=reply_markup), self)
        else:
            return MessageAdapter(await self.raw.send_file(chat_id, audio, caption=caption, buttons=reply_markup, voice_note=False), self)

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None):
        if self.platform == Platform.BALE:
            return MessageAdapter(await self.raw.send_voice(chat_id, voice, caption=caption, reply_markup=reply_markup), self)
        else:
            return MessageAdapter(await self.raw.send_file(chat_id, voice, caption=caption, buttons=reply_markup, voice_note=True), self)

    async def get_chat_member(self, chat_id, user_id):
        if self.platform == Platform.BALE:
            try:
                member = await self.raw.get_chat_member(chat_id, user_id)
                return member
            except:
                return None
        else:
            try:
                from telethon.tl.functions.channels import GetParticipantRequest
                from telethon.tl.types import ChannelParticipantMember, ChannelParticipantAdmin, ChannelParticipantCreator
                participant = await self.raw(GetParticipantRequest(chat_id, user_id))
                p = participant.participant
                class MockMember:
                    def __init__(self, status): self.status = status
                if isinstance(p, ChannelParticipantCreator): return MockMember("creator")
                if isinstance(p, ChannelParticipantAdmin): return MockMember("administrator")
                return MockMember("member")
            except:
                return None

    async def get_chat(self, chat_id):
        if self.platform == Platform.BALE:
            return await self.raw.get_chat(chat_id)
        else:
            chat = await self.raw.get_entity(chat_id)
            class MockChat:
                def __init__(self, type): self.type = type
            ctype = "private" if getattr(chat, 'is_private', False) else "group"
            return MockChat(ctype)

    async def run_forever(self):
        if self.platform == Platform.BALE:
            # Balethon's run is blocking and not easily awaited if it uses its own loop
            # But we can use bot.connect() then wait
            await self.raw.start()
            self.username = self.raw.user.username
            while True:
                await asyncio.sleep(3600)
        else:
            await self.raw.run_until_disconnected()

def InlineKeyboardButton(text, callback_data=None, url=None, web_app=None, copy_text=None):
    if CURRENT_PLATFORM == Platform.BALE:
        return BaleInlineKeyboardButton(text=text, callback_data=callback_data, url=url, web_app=web_app, copy_text=copy_text)
    else:
        if url: return Button.url(text, url)
        if callback_data: return Button.inline(text, callback_data)
        if web_app: return Button.url(text, web_app)
        if copy_text: return Button.inline(text, f"copy:{copy_text}")
        return Button.inline(text, "ignore")

def InlineKeyboard(*rows):
    if CURRENT_PLATFORM == Platform.BALE:
        return BaleInlineKeyboard(*rows)
    else:
        return rows
