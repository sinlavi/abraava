from core.config import PLATFORM, BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, PROXY
from core.logger import logger
import asyncio

# Platform-specific imports
if PLATFORM == "telegram":
    from telethon import TelegramClient, events, Button as TButton
    from telethon.tl.types import PeerChannel, PeerChat, PeerUser
    from telethon.utils import pack_bot_file_id
else:
    from balethon import Client as BalethonClient
    from balethon.objects import Message as BaleMessage, CallbackQuery as BaleCallbackQuery, InlineKeyboard, InlineKeyboardButton

class Button:
    def __init__(self, text, url=None, callback_data=None, copy_text=None, web_app=None):
        self.text = text
        self.url = url
        self.callback_data = callback_data
        self.copy_text = copy_text
        self.web_app = web_app

class WrappedMessage:
    def __init__(self, raw_message, platform):
        self.raw = raw_message
        self.platform = platform
        self.client = raw_message.client

        if platform == "telegram":
            self.id = raw_message.id
            self.content = raw_message.message or ""
            self.caption = raw_message.message or ""
            self.author = raw_message.sender
            self.chat = raw_message.chat
            self.reply_to_message = raw_message.reply_to
        else:
            self.id = raw_message.id
            self.content = raw_message.content
            self.caption = raw_message.caption
            self.author = raw_message.author
            self.chat = raw_message.chat
            self.reply_to_message = raw_message.reply_to_message

    @property
    def file_id(self):
        if self.platform == "telegram":
            if self.raw.media:
                return pack_bot_file_id(self.raw.media)
            return None
        else:
            if hasattr(self.raw, "audio") and self.raw.audio: return self.raw.audio.id
            if hasattr(self.raw, "video") and self.raw.video: return self.raw.video.id
            if hasattr(self.raw, "document") and self.raw.document: return self.raw.document.id
            if hasattr(self.raw, "photo") and self.raw.photo: return self.raw.photo.id
            return None

    async def reply(self, text, reply_markup=None):
        return await self.client.send_message(self.chat.id, text, reply_to=self.id, reply_markup=reply_markup)

    async def edit(self, text, reply_markup=None):
        return await self.client.edit_message(self.chat.id, self.id, text, reply_markup=reply_markup)

    async def delete(self):
        await self.raw.delete()

class WrappedCallbackQuery:
    def __init__(self, raw_query, platform):
        self.raw = raw_query
        self.platform = platform
        self.id = raw_query.id
        self.client = raw_query.client

        if platform == "telegram":
            self.data = raw_query.data.decode() if isinstance(raw_query.data, bytes) else raw_query.data
            self.author = raw_query.sender
            self.message = WrappedMessage(raw_query.message, platform) if raw_query.message else None
        else:
            self.data = raw_query.data
            self.author = raw_query.author
            self.message = WrappedMessage(raw_query.message, platform) if raw_query.message else None

    async def answer(self, text=None, show_alert=False):
        if self.platform == "telegram":
            await self.raw.answer(message=text, alert=show_alert)
        else:
            await self.raw.answer(text=text, show_alert=show_alert)

class BotClient:
    def __init__(self):
        self.platform = PLATFORM
        self.token = BOT_TOKEN
        self.handlers = {"message": [], "callback_query": []}

        if self.platform == "telegram":
            self.client = TelegramClient('abraava_session', TELEGRAM_API_ID, TELEGRAM_API_HASH, proxy=self._parse_proxy(PROXY))
        else:
            self.client = BalethonClient(token=self.token, proxy=PROXY)

    def _parse_proxy(self, proxy_url):
        if not proxy_url: return None
        import socks
        try:
            proto, rest = proxy_url.split("://")
            host, port = rest.split(":")
            return (socks.SOCKS5, host, int(port), True)
        except:
            return None

    def on_message(self):
        def decorator(func):
            self.handlers["message"].append(func)
            return func
        return decorator

    def on_callback_query(self):
        def decorator(func):
            self.handlers["callback_query"].append(func)
            return func
        return decorator

    async def _handle_telegram_message(self, event):
        wrapped = WrappedMessage(event.message, "telegram")
        for handler in self.handlers["message"]:
            asyncio.create_task(handler(wrapped))

    async def _handle_telegram_callback(self, event):
        wrapped = WrappedCallbackQuery(event, "telegram")
        for handler in self.handlers["callback_query"]:
            asyncio.create_task(handler(wrapped))

    def run(self, on_startup=None):
        if self.platform == "telegram":
            loop = self.client.loop
            loop.run_until_complete(self.client.start(bot_token=self.token))
            if on_startup:
                loop.run_until_complete(on_startup())

            @self.client.on(events.NewMessage)
            async def msg_handler(event):
                await self._handle_telegram_message(event)

            @self.client.on(events.CallbackQuery)
            async def cb_handler(event):
                await self._handle_telegram_callback(event)

            logger.info("Bot (Telegram) is running...")
            self.client.run_until_disconnected()
        else:
            if on_startup:
                # Balethon on_initialize decorator is used in main.py,
                # but let's support explicit callback here too
                @self.client.on_initialize()
                async def startup():
                    await on_startup()

            @self.client.on_message()
            async def msg_handler(message):
                wrapped = WrappedMessage(message, "bale")
                for handler in self.handlers["message"]:
                    await handler(wrapped)

            @self.client.on_callback_query()
            async def cb_handler(callback_query):
                wrapped = WrappedCallbackQuery(callback_query, "bale")
                for handler in self.handlers["callback_query"]:
                    await handler(wrapped)

            logger.info("Bot (Bale) is running...")
            self.client.run()

    async def send_message(self, chat_id, text, reply_markup=None, reply_to=None):
        markup = self._convert_markup(reply_markup)
        if self.platform == "telegram":
            return WrappedMessage(await self.client.send_message(chat_id, text, buttons=markup, reply_to=reply_to), "telegram")
        else:
            return WrappedMessage(await self.client.send_message(chat_id, text, reply_markup=markup, reply_to_message_id=reply_to), "bale")

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        markup = self._convert_markup(reply_markup)
        if self.platform == "telegram":
            return WrappedMessage(await self.client.edit_message(chat_id, message_id, text, buttons=markup), "telegram")
        else:
            return WrappedMessage(await self.client.edit_message(chat_id, message_id, text, reply_markup=markup), "bale")

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to=None):
        markup = self._convert_markup(reply_markup)
        if self.platform == "telegram":
            return WrappedMessage(await self.client.send_file(chat_id, photo, caption=caption, buttons=markup, reply_to=reply_to), "telegram")
        else:
            return WrappedMessage(await self.client.send_photo(chat_id, photo, caption=caption, reply_markup=markup, reply_to_message_id=reply_to), "bale")

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, reply_to=None):
        markup = self._convert_markup(reply_markup)
        if self.platform == "telegram":
            return WrappedMessage(await self.client.send_file(chat_id, audio, caption=caption, buttons=markup, reply_to=reply_to, voice=False), "telegram")
        else:
            return WrappedMessage(await self.client.send_audio(chat_id, audio, caption=caption, reply_markup=markup, reply_to_message_id=reply_to), "bale")

    async def get_chat(self, chat_id):
        if self.platform == "telegram":
            return await self.client.get_entity(chat_id)
        else:
            return await self.client.get_chat(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        if self.platform == "telegram":
            from telethon.tl.functions.channels import GetParticipantRequest
            try:
                participant = await self.client(GetParticipantRequest(channel=chat_id, participant=user_id))
                return participant.participant
            except:
                return None
        else:
            return await self.client.get_chat_member(chat_id, user_id)

    def _convert_markup(self, markup):
        if not markup: return None
        if self.platform == "telegram":
            if isinstance(markup, list):
                telegram_rows = []
                for row in markup:
                    if isinstance(row, list):
                        telegram_row = []
                        for btn in row:
                            if hasattr(btn, 'url') and btn.url:
                                telegram_row.append(TButton.url(btn.text, btn.url))
                            elif hasattr(btn, 'callback_data') and btn.callback_data:
                                telegram_row.append(TButton.inline(btn.text, btn.callback_data))
                            elif hasattr(btn, 'copy_text') and btn.copy_text:
                                telegram_row.append(TButton.inline(btn.text, f"copy:{btn.copy_text}"))
                        telegram_rows.append(telegram_row)
                return telegram_rows
            return markup
        else:
            if isinstance(markup, list):
                return InlineKeyboard(*[
                    [
                        InlineKeyboardButton(text=btn.text, url=getattr(btn, 'url', None),
                                             callback_data=getattr(btn, 'callback_data', None),
                                             copy_text=getattr(btn, 'copy_text', None))
                        for btn in row
                    ] if isinstance(row, list) else row
                    for row in markup
                ])
            return markup

    async def get_me(self):
        if self.platform == "telegram":
            return await self.client.get_me()
        else:
            return self.client.user

    async def send_chat_action(self, chat_id, action):
        if self.platform == "telegram":
            tl_action = action.replace("_", "-")
            if tl_action == "record-voice": tl_action = "record-audio"
            if tl_action == "upload-voice": tl_action = "upload-audio"

            try:
                from telethon.tl.functions.messages import SetTypingRequest
                from telethon.tl.types import SendMessageTypingAction, SendMessageUploadPhotoAction, SendMessageRecordAudioAction, SendMessageUploadAudioAction

                act_map = {
                    "typing": SendMessageTypingAction(),
                    "upload-photo": SendMessageUploadPhotoAction(0),
                    "record-audio": SendMessageRecordAudioAction(),
                    "upload-audio": SendMessageUploadAudioAction(0)
                }
                if tl_action in act_map:
                    await self.client(SetTypingRequest(peer=chat_id, action=act_map[tl_action]))
            except: pass
        else:
            await self.client.send_chat_action(chat_id, action)
