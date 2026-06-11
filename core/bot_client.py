from core.config import PLATFORM, BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, PROXY
from core.logger import logger
import asyncio
import os

if PLATFORM == "telegram":
    from telethon import TelegramClient, events, Button, utils
    import telethon.functions as functions
    import telethon.types as types
else:
    from balethon import Client
    from balethon.objects import InlineKeyboard, InlineKeyboardButton

class WrappedMessage:
    def __init__(self, message, platform):
        self.raw = message
        self.platform = platform
        if platform == "telegram":
            self.id = message.id
            sender = message.sender
            self.author = type('Author', (), {
                'id': message.sender_id,
                'is_bot': getattr(sender, 'bot', False) if sender else False,
                'username': getattr(sender, 'username', None),
                'first_name': getattr(sender, 'first_name', None)
            })
            self.chat = type('Chat', (), {
                'id': message.chat_id,
                'type': 'private' if message.is_private else 'group' if message.is_group or message.is_supergroup else 'channel' if message.is_channel else 'unknown'
            })
            self.content = message.text
            self.caption = message.caption
            self.reply_to_message = None
            if message.reply_to:
                # We can't easily fetch full reply message here without await, so we mock it
                self.reply_to_message = type('Reply', (), {
                    'id': message.reply_to.reply_to_msg_id,
                    'author': type('Author', (), {'id': None}) # ID unknown without fetch
                })
        else:
            self.id = message.id
            self.author = message.author
            self.chat = message.chat
            self.content = message.content
            self.reply_to_message = message.reply_to_message

    async def reply(self, text, reply_markup=None):
        return await self.client_wrapper.send_message(self.chat.id, text, reply_markup=reply_markup, reply_to_message_id=self.id)

    async def edit(self, text, reply_markup=None):
        return await self.client_wrapper.edit_message(self.chat.id, self.id, text, reply_markup=reply_markup)

    async def delete(self):
        return await self.client_wrapper.delete_message(self.chat.id, self.id)

class WrappedCallbackQuery:
    def __init__(self, query, platform):
        self.raw = query
        self.platform = platform
        if platform == "telegram":
            self.id = query.id
            self.author = type('Author', (), {'id': query.sender_id})
            self.data = query.data.decode() if isinstance(query.data, bytes) else query.data
            self.message = WrappedMessage(query.message, platform) if query.message else None
        else:
            self.id = query.id
            self.author = query.author
            self.data = query.data
            self.message = WrappedMessage(query.message, platform) if query.message else None

class BotClient:
    def __init__(self):
        self.platform = PLATFORM
        self.proxy = PROXY
        self._message_handlers = []
        self._callback_handlers = []
        self._init_handlers = []
        self._shutdown_handlers = []

        if PLATFORM == "telegram":
            proxy_config = None
            if PROXY:
                try:
                    import socks
                    p = PROXY.replace("socks5h://", "").replace("socks5://", "")
                    if "@" in p:
                        auth, addr = p.split("@")
                        user, pwd = auth.split(":")
                        host, port = addr.split(":")
                    else:
                        host, port = p.split(":")
                        user, pwd = None, None
                    proxy_config = (socks.SOCKS5, host, int(port), True, user, pwd)
                except Exception as e:
                    logger.error(f"Failed to configure TG proxy: {e}")

            api_id = int(TELEGRAM_API_ID) if TELEGRAM_API_ID else 0
            self.client = TelegramClient("abraava_tg", api_id, TELEGRAM_API_HASH, proxy=proxy_config)
            self.client.on(events.NewMessage(incoming=True))(self._tg_on_message)
            self.client.on(events.CallbackQuery())(self._tg_on_callback)
        else:
            self.client = Client(token=BOT_TOKEN or "", proxy=PROXY)
            self.client.on_message()(self._bale_on_message)
            self.client.on_callback_query()(self._bale_on_callback)
            self.client.on_initialize()(self._bale_on_init)
            self.client.on_shutdown()(self._bale_on_shutdown)

    async def _tg_on_message(self, event):
        wrapped = WrappedMessage(event.message, "telegram")
        wrapped.client_wrapper = self
        for handler in self._message_handlers:
            await handler(wrapped)

    async def _tg_on_callback(self, event):
        wrapped = WrappedCallbackQuery(event, "telegram")
        wrapped.message.client_wrapper = self
        for handler in self._callback_handlers:
            await handler(wrapped)

    async def _bale_on_message(self, message):
        wrapped = WrappedMessage(message, "bale")
        wrapped.client_wrapper = self
        for handler in self._message_handlers:
            await handler(wrapped)

    async def _bale_on_callback(self, query):
        wrapped = WrappedCallbackQuery(query, "bale")
        wrapped.message.client_wrapper = self
        for handler in self._callback_handlers:
            await handler(wrapped)

    async def _bale_on_init(self):
        for handler in self._init_handlers:
            await handler()

    async def _bale_on_shutdown(self):
        for handler in self._shutdown_handlers:
            await handler()

    def on_message(self):
        def decorator(handler):
            self._message_handlers.append(handler)
            return handler
        return decorator

    def on_callback_query(self):
        def decorator(handler):
            self._callback_handlers.append(handler)
            return handler
        return decorator

    def on_initialize(self):
        def decorator(handler):
            self._init_handlers.append(handler)
            return handler
        return decorator

    def on_shutdown(self):
        def decorator(handler):
            self._shutdown_handlers.append(handler)
            return handler
        return decorator

    @property
    def user(self):
        if self.platform == "telegram":
            return type('User', (), {'id': self._tg_me.id, 'username': self._tg_me.username})
        else:
            return self.client.user

    async def start(self):
        if self.platform == "telegram":
            await self.client.start(bot_token=BOT_TOKEN)
            self._tg_me = await self.client.get_me()
            for handler in self._init_handlers:
                await handler()
        else:
            await self.client.connect()

    def _convert_keyboard(self, keyboard):
        if not keyboard: return None
        if self.platform == "telegram":
            rows = []
            for row in keyboard:
                tg_row = []
                for btn in row:
                    if isinstance(btn, dict):
                        if btn.get("url"):
                            tg_row.append(Button.url(btn["text"], btn["url"]))
                        elif btn.get("callback_data"):
                            tg_row.append(Button.inline(btn["text"], btn["callback_data"]))
                        elif btn.get("copy_text"):
                            # Telegram doesn't support copy_text directly, use a callback or just a plain button
                            tg_row.append(Button.inline(btn["text"], f"copy:{btn['copy_text'][:32]}"))
                        else:
                            # Fallback
                            tg_row.append(Button.inline(btn["text"], "ignore"))
                    else:
                        tg_row.append(btn)
                rows.append(tg_row)
            return rows
        else:
            rows = []
            for row in keyboard:
                bale_row = []
                for btn in row:
                    if isinstance(btn, dict):
                        bale_row.append(InlineKeyboardButton(
                            text=btn["text"],
                            url=btn.get("url"),
                            callback_data=btn.get("callback_data"),
                            copy_text=btn.get("copy_text")
                        ))
                    else:
                        bale_row.append(btn)
                rows.append(bale_row)
            return InlineKeyboard(*rows)

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        if self.platform == "telegram":
            return WrappedMessage(await self.client.send_message(chat_id, text, buttons=markup, reply_to=reply_to_message_id, parse_mode='md'), "telegram")
        else:
            msg = await self.client.send_message(chat_id, text, reply_markup=markup, reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        markup = self._convert_keyboard(reply_markup)
        if self.platform == "telegram":
            try:
                msg = await self.client.edit_message(chat_id, message_id, text, buttons=markup, parse_mode='md')
                wrapped = WrappedMessage(msg, "telegram")
                wrapped.client_wrapper = self
                return wrapped
            except Exception as e:
                if "message is not modified" in str(e).lower(): return None
                raise
        else:
            try:
                msg = await self.client.edit_message(chat_id, message_id, text, reply_markup=markup)
                wrapped = WrappedMessage(msg, "bale")
                wrapped.client_wrapper = self
                return wrapped
            except Exception as e:
                if "message is not modified" in str(e).lower(): return None
                raise

    async def delete_message(self, chat_id, message_id):
        if self.platform == "telegram":
            await self.client.delete_messages(chat_id, [message_id])
        else:
            await self.client.delete_message(chat_id, message_id)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        if self.platform == "telegram":
            msg = await self.client.send_file(chat_id, photo, caption=caption, buttons=markup, reply_to=reply_to_message_id)
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            return wrapped
        else:
            msg = await self.client.send_photo(chat_id, photo, caption=caption, reply_markup=markup, reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, reply_to_message_id=None, **kwargs):
        markup = self._convert_keyboard(reply_markup)
        if self.platform == "telegram":
            attributes = [types.DocumentAttributeAudio(
                duration=int(kwargs.get('duration', 0)),
                title=kwargs.get('title'),
                performer=kwargs.get('performer')
            )]
            thumb = kwargs.get('thumb')
            msg = await self.client.send_file(chat_id, audio, caption=caption, buttons=markup, reply_to=reply_to_message_id, attributes=attributes, thumb=thumb, voice=False)
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            return wrapped
        else:
            msg = await self.client.send_audio(chat_id, audio, caption=caption, reply_markup=markup, reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        if self.platform == "telegram":
            msg = await self.client.send_file(chat_id, voice, caption=caption, buttons=markup, reply_to=reply_to_message_id, voice=True)
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            return wrapped
        else:
            msg = await self.client.send_voice(chat_id, voice, caption=caption, reply_markup=markup, reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped

    async def get_chat(self, chat_id):
        if self.platform == "telegram":
            try:
                chat = await self.client.get_entity(chat_id)
                return type('Chat', (), {
                    'id': chat.id,
                    'type': 'private' if isinstance(chat, types.User) else 'group' if isinstance(chat, (types.Chat, types.Channel)) and not getattr(chat, 'broadcast', False) else 'channel'
                })
            except Exception as e:
                logger.error(f"TG get_chat error: {e}")
                return None
        else:
            return await self.client.get_chat(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        if self.platform == "telegram":
            from telethon.errors import UserNotParticipantError
            try:
                # For Telethon, we check if user is in the chat
                p = await self.client.get_permissions(chat_id, user_id)
                # status can be 'member', 'administrator', 'creator' (left is handled by exception)
                status = 'member'
                if p.is_admin: status = 'administrator'
                if p.is_creator: status = 'creator'
                return type('ChatMember', (), {'status': status})
            except UserNotParticipantError:
                return type('ChatMember', (), {'status': 'left'})
            except Exception as e:
                if "not a participant" in str(e).lower(): return type('ChatMember', (), {'status': 'left'})
                logger.error(f"TG get_chat_member error: {e}")
                return None
        else:
            return await self.client.get_chat_member(chat_id, user_id)

    async def forward_message(self, chat_id, message_id, from_chat_id):
        if self.platform == "telegram":
            return await self.client.forward_messages(chat_id, message_id, from_chat_id)
        else:
            return await self.client.forward_message(chat_id, message_id, from_chat_id)

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        if self.platform == "telegram":
            await self.client(functions.messages.SetBotCallbackAnswerRequest(
                query_id=int(callback_query_id),
                message=text,
                alert=show_alert
            ))
        else:
            await self.client.answer_callback_query(callback_query_id, text, show_alert)

    async def send_chat_action(self, chat_id, action):
        if self.platform == "telegram":
            tg_action = {
                "typing": types.SendMessageTypingAction(),
                "upload_photo": types.SendMessageUploadPhotoAction(0),
                "record_audio": types.SendMessageRecordAudioAction(),
                "upload_audio": types.SendMessageUploadAudioAction(0),
                "record_video": types.SendMessageRecordVideoAction(),
                "upload_video": types.SendMessageUploadVideoAction(0),
                "upload_document": types.SendMessageUploadDocumentAction(0),
            }.get(action, types.SendMessageTypingAction())
            await self.client(functions.messages.SetTypingRequest(
                peer=chat_id,
                action=tg_action
            ))
        else:
            await self.client.send_chat_action(chat_id, action)

    def run(self):
        if self.platform == "telegram":
            self.client.loop.run_until_complete(self.client.start(bot_token=BOT_TOKEN))
            self._tg_me = self.client.loop.run_until_complete(self.client.get_me())
            for handler in self._init_handlers:
                if asyncio.iscoroutinefunction(handler):
                    self.client.loop.run_until_complete(handler())
                else:
                    handler()

            self.client.run_until_disconnected()

            for handler in self._shutdown_handlers:
                if asyncio.iscoroutinefunction(handler):
                    self.client.loop.run_until_complete(handler())
                else:
                    handler()
        else:
            self.client.run()
