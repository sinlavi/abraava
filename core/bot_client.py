from core.config import PLATFORM, BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, PROXY
from core.logger import logger
import asyncio
import os
from datetime import datetime

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
            
            # Safe access to text and caption
            self.content = getattr(message, 'text', None) or getattr(message, 'caption', None)
            self.caption = getattr(message, 'caption', None)
            
            self.reply_to_message = None
            
            if hasattr(message, 'reply_to') and message.reply_to:
                self.reply_to_message = type('Reply', (), {
                    'id': message.reply_to.reply_to_msg_id,
                    'author': type('Author', (), {'id': None})
                })
            
            # Handle media attributes
            self.photo = None
            self.document = None
            self.audio = None
            self.voice = None
            self.video = None
            self.animation = None
            self.sticker = None
            self.media_type = "text"
            
            if hasattr(message, 'photo') and message.photo:
                self.photo = message.photo[-1] if isinstance(message.photo, list) else message.photo
                self.media_type = "photo"
                if hasattr(message, 'caption') and message.caption:
                    self.content = message.caption
            elif hasattr(message, 'document') and message.document:
                self.document = message.document
                self.media_type = "document"
                
                for attr in message.document.attributes:
                    if isinstance(attr, types.DocumentAttributeAudio):
                        self.audio = message.document
                        self.media_type = "audio"
                        break
                    elif isinstance(attr, types.DocumentAttributeVideo):
                        self.video = message.document
                        self.media_type = "video"
                        break
                    elif isinstance(attr, types.DocumentAttributeAnimated):
                        self.animation = message.document
                        self.media_type = "animation"
                        break
                    elif isinstance(attr, types.DocumentAttributeSticker):
                        self.sticker = message.document
                        self.media_type = "sticker"
                        break
            elif hasattr(message, 'voice') and message.voice:
                self.voice = message.voice
                self.media_type = "voice"
            elif hasattr(message, 'video') and message.video:
                self.video = message.video
                self.media_type = "video"
            elif hasattr(message, 'animation') and message.animation:
                self.animation = message.animation
                self.media_type = "animation"
            elif hasattr(message, 'sticker') and message.sticker:
                self.sticker = message.sticker
                self.media_type = "sticker"
                
        else:  # Bale platform
            self.id = message.id
            self.author = message.author
            self.chat = message.chat
            self.content = getattr(message, 'content', None)
            self.reply_to_message = getattr(message, 'reply_to_message', None)
            
            self.photo = getattr(message, 'photo', None)
            self.document = getattr(message, 'document', None)
            self.audio = getattr(message, 'audio', None)
            self.voice = getattr(message, 'voice', None)
            self.video = getattr(message, 'video', None)
            self.animation = getattr(message, 'animation', None)
            self.sticker = getattr(message, 'sticker', None)
            self.caption = getattr(message, 'caption', None)
            self.media_type = getattr(message, 'media_type', 'text')

    async def reply(self, text, reply_markup=None):
        return await self.client_wrapper.send_message(
            self.chat.id, text, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def reply_photo(self, photo, caption=None, reply_markup=None):
        return await self.client_wrapper.send_photo(
            self.chat.id, photo, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def reply_audio(self, audio, caption=None, reply_markup=None, **kwargs):
        return await self.client_wrapper.send_audio(
            self.chat.id, audio, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id, 
            **kwargs
        )

    async def reply_voice(self, voice, caption=None, reply_markup=None):
        return await self.client_wrapper.send_voice(
            self.chat.id, voice, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def edit(self, text, reply_markup=None):
        return await self.client_wrapper.edit_message(
            self.chat.id, self.id, 
            text, 
            reply_markup=reply_markup
        )

    async def delete(self):
        return await self.client_wrapper.delete_message(self.chat.id, self.id)
    
    async def download_media(self, file_path=None):
        if not self.has_media:
            return None
            
        if self.platform == "telegram":
            return await self.client_wrapper.client.download_media(self.raw, file=file_path)
        else:
            if self.photo:
                return await self.client_wrapper.client.download_photo(self.photo, file_path)
            elif self.document:
                return await self.client_wrapper.client.download_document(self.document, file_path)
            elif self.audio:
                return await self.client_wrapper.client.download_audio(self.audio, file_path)
            elif self.voice:
                return await self.client_wrapper.client.download_voice(self.voice, file_path)
            elif self.video:
                return await self.client_wrapper.client.download_video(self.video, file_path)
        return None
    
    @property
    def has_media(self):
        return any([
            self.photo, self.document, self.audio, 
            self.voice, self.video, self.animation, 
            self.sticker
        ])
    
    @property
    def file_id(self):
        if self.platform != "telegram":
            if self.photo:
                return self.photo.file_id
            elif self.document:
                return self.document.file_id
            elif self.audio:
                return self.audio.file_id
            elif self.voice:
                return self.voice.file_id
            elif self.video:
                return self.video.file_id
        return None
    
    @property
    def message_link(self):
        if self.platform == "telegram":
            if self.chat.type == "channel" or self.chat.type == "supergroup":
                username = getattr(self.chat, 'username', None)
                if username:
                    return f"https://t.me/{username}/{self.id}"
                else:
                    chat_id_str = str(self.chat.id)
                    if chat_id_str.startswith('-100'):
                        chat_id_str = chat_id_str[4:]
                    return f"https://t.me/c/{chat_id_str}/{self.id}"
        return None

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

    async def answer(self, text=None, show_alert=False):
        return await self.client_wrapper.answer_callback_query(self.id, text, show_alert)
    
    async def edit_message(self, text, reply_markup=None):
        if self.message:
            return await self.message.edit(text, reply_markup)
        return None
    
    async def delete_message(self):
        if self.message:
            return await self.message.delete()
        return None

class BotClient:
    def __init__(self):
        self.platform = PLATFORM
        self.proxy = PROXY
        self._message_handlers = []
        self._callback_handlers = []
        self._init_handlers = []
        self._shutdown_handlers = []
        self._error_handlers = []
        self._running = False

        if PLATFORM == "telegram":
            proxy_config = None
            if PROXY:
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

            self.client = TelegramClient(
                "abraava_tg", 
                int(TELEGRAM_API_ID), 
                TELEGRAM_API_HASH, 
                proxy=proxy_config
            )
            
            # Register event handlers
            @self.client.on(events.NewMessage)
            async def tg_message_handler(event):
                await self._tg_on_message(event)
            
            @self.client.on(events.CallbackQuery)
            async def tg_callback_handler(event):
                await self._tg_on_callback(event)
                
        else:
            self.client = Client(token=BOT_TOKEN, proxy=PROXY)
            self.client.on_message()(self._bale_on_message)
            self.client.on_callback_query()(self._bale_on_callback)
            self.client.on_initialize()(self._bale_on_init)
            self.client.on_shutdown()(self._bale_on_shutdown)

    async def _handle_error(self, error, context=None):
        for handler in self._error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error, context)
                else:
                    handler(error, context)
            except Exception as e:
                logger.error(f"Error in error handler: {e}")

    async def _tg_on_message(self, event):
        try:
            # Get message text safely
            message_text = getattr(event.message, 'text', None) or getattr(event.message, 'caption', None)
            sender = await event.get_sender()
            sender_name = sender.first_name if sender else "Unknown"
            
            # Log like Balethon style
            logger.info(f"📩 New message from {sender_name} (ID: {event.sender_id}) in chat {event.chat_id}: {message_text}")
            
            wrapped = WrappedMessage(event.message, "telegram")
            wrapped.client_wrapper = self
            
            if not self._message_handlers:
                logger.warning("⚠️ No message handlers registered!")
                return
                
            for handler in self._message_handlers:
                try:
                    await handler(wrapped)
                    logger.debug(f"✅ Message handled by {handler.__name__}")
                except Exception as e:
                    logger.error(f"❌ Error in handler {handler.__name__}: {e}")
                    await self._handle_error(e, {"handler": handler, "message": wrapped})
        except Exception as e:
            logger.error(f"❌ Error in message handler: {e}")
            import traceback
            traceback.print_exc()
            await self._handle_error(e, {"event": "message", "platform": "telegram"})

    async def _tg_on_callback(self, event):
        try:
            logger.info(f"🔘 Callback query received: {event.data}")
            
            wrapped = WrappedCallbackQuery(event, "telegram")
            if wrapped.message:
                wrapped.message.client_wrapper = self
            wrapped.client_wrapper = self
            
            if not self._callback_handlers:
                logger.warning("⚠️ No callback handlers registered!")
                return
                
            for handler in self._callback_handlers:
                try:
                    await handler(wrapped)
                    logger.debug(f"✅ Callback handled by {handler.__name__}")
                except Exception as e:
                    logger.error(f"❌ Error in callback handler {handler.__name__}: {e}")
                    await self._handle_error(e, {"handler": handler, "callback": wrapped})
        except Exception as e:
            logger.error(f"❌ Error in callback handler: {e}")
            await self._handle_error(e, {"event": "callback", "platform": "telegram"})

    async def _bale_on_message(self, message):
        try:
            sender_name = message.author.first_name if hasattr(message.author, 'first_name') else str(message.author.id)
            logger.info(f"📩 New message from {sender_name} (ID: {message.author.id}) in chat {message.chat.id}: {message.content}")
            
            wrapped = WrappedMessage(message, "bale")
            wrapped.client_wrapper = self
            for handler in self._message_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler, "message": wrapped})
        except Exception as e:
            await self._handle_error(e, {"event": "message", "platform": "bale"})

    async def _bale_on_callback(self, callback_query):
        try:
            logger.info(f"🔘 Callback query received: {callback_query.data}")
            
            query = callback_query
            wrapped = WrappedCallbackQuery(query, "bale")
            if wrapped.message:
                wrapped.message.client_wrapper = self
            wrapped.client_wrapper = self
            for handler in self._callback_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler, "callback": wrapped})
        except Exception as e:
            await self._handle_error(e, {"event": "callback", "platform": "bale"})

    async def _bale_on_init(self):
        logger.info("🚀 Bot initializing...")
        for handler in self._init_handlers:
            try:
                await handler()
            except Exception as e:
                await self._handle_error(e, {"handler": handler, "event": "init"})
        logger.info("✅ Bot initialization complete")

    async def _bale_on_shutdown(self):
        logger.info("🛑 Bot shutting down...")
        for handler in self._shutdown_handlers:
            try:
                await handler()
            except Exception as e:
                await self._handle_error(e, {"handler": handler, "event": "shutdown"})
        logger.info("✅ Bot shutdown complete")

    def on_message(self):
        def decorator(handler):
            self._message_handlers.append(handler)
            logger.info(f"✅ Message handler registered: {handler.__name__}")
            return handler
        return decorator

    def on_callback_query(self):
        def decorator(handler):
            self._callback_handlers.append(handler)
            logger.info(f"✅ Callback handler registered: {handler.__name__}")
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
    
    def on_error(self):
        def decorator(handler):
            self._error_handlers.append(handler)
            return handler
        return decorator

    @property
    def user(self):
        if self.platform == "telegram":
            if hasattr(self, '_tg_me'):
                return type('User', (), {
                    'id': self._tg_me.id, 
                    'username': self._tg_me.username,
                    'first_name': self._tg_me.first_name,
                    'last_name': getattr(self._tg_me, 'last_name', None),
                    'is_bot': getattr(self._tg_me, 'bot', True)
                })
            return None
        else:
            return self.client.user

    async def start(self):
        if self.platform == "telegram":
            await self.client.start(bot_token=BOT_TOKEN)
            self._tg_me = await self.client.get_me()
            logger.info(f"✨ Bot started as @{self._tg_me.username} (ID: {self._tg_me.id})")
            for handler in self._init_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                except Exception as e:
                    await self._handle_error(e, {"handler": handler, "event": "init"})
        else:
            await self.client.connect()

    def _convert_keyboard(self, keyboard):
        if not keyboard: 
            return None
            
        if self.platform == "telegram":
            rows = []
            for row in keyboard:
                tg_row = []
                for btn in row:
                    if isinstance(btn, dict):
                        if btn.get("url"):
                            tg_row.append(Button.url(btn["text"], btn["url"]))
                        else:
                            tg_row.append(Button.inline(btn["text"], btn["callback_data"]))
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
                            callback_data=btn.get("callback_data")
                        ))
                    else:
                        bale_row.append(btn)
                rows.append(bale_row)
            return InlineKeyboard(*rows)

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode='md'):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            result = await self.client.send_message(
                chat_id, text, 
                buttons=markup, 
                reply_to=reply_to_message_id, 
                parse_mode=parse_mode
            )
            wrapped = WrappedMessage(result, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"📤 Message sent to {chat_id}: {text[:50]}...")
            return wrapped
        else:
            msg = await self.client.send_message(
                chat_id, text, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"📤 Message sent to {chat_id}: {text[:50]}...")
            return wrapped

    async def edit_message(self, chat_id, message_id, text, reply_markup=None, parse_mode='md'):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            try:
                msg = await self.client.edit_message(
                    chat_id, message_id, text, 
                    buttons=markup, 
                    parse_mode=parse_mode
                )
                if msg:
                    wrapped = WrappedMessage(msg, "telegram")
                    wrapped.client_wrapper = self
                    logger.debug(f"✏️ Message {message_id} edited in chat {chat_id}")
                    return wrapped
                return None
            except Exception as e:
                if "message is not modified" in str(e).lower(): 
                    return None
                raise
        else:
            try:
                msg = await self.client.edit_message_text(
                    chat_id, message_id, text, 
                    reply_markup=markup
                )
                wrapped = WrappedMessage(msg, "bale")
                wrapped.client_wrapper = self
                logger.debug(f"✏️ Message {message_id} edited in chat {chat_id}")
                return wrapped
            except Exception as e:
                if "message is not modified" in str(e).lower(): 
                    return None
                raise

    async def delete_message(self, chat_id, message_id):
        if self.platform == "telegram":
            await self.client.delete_messages(chat_id, [message_id])
            logger.debug(f"🗑️ Message {message_id} deleted from chat {chat_id}")
        else:
            await self.client.delete_message(chat_id, message_id)
            logger.debug(f"🗑️ Message {message_id} deleted from chat {chat_id}")

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            msg = await self.client.send_file(
                chat_id, photo, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"📸 Photo sent to chat {chat_id}")
            return wrapped
        else:
            msg = await self.client.send_photo(
                chat_id, photo, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"📸 Photo sent to chat {chat_id}")
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
            msg = await self.client.send_file(
                chat_id, audio, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id, 
                attributes=attributes, 
                thumb=thumb, 
                voice=False
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"🎵 Audio sent to chat {chat_id}")
            return wrapped
        else:
            msg = await self.client.send_audio(
                chat_id, audio, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"🎵 Audio sent to chat {chat_id}")
            return wrapped

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            msg = await self.client.send_file(
                chat_id, voice, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id, 
                voice=True
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"🎤 Voice message sent to chat {chat_id}")
            return wrapped
        else:
            msg = await self.client.send_voice(
                chat_id, voice, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"🎤 Voice message sent to chat {chat_id}")
            return wrapped

    async def send_document(self, chat_id, document, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            msg = await self.client.send_file(
                chat_id, document, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"📄 Document sent to chat {chat_id}")
            return wrapped
        else:
            msg = await self.client.send_document(
                chat_id, document, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"📄 Document sent to chat {chat_id}")
            return wrapped

    async def send_video(self, chat_id, video, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            msg = await self.client.send_file(
                chat_id, video, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.debug(f"🎥 Video sent to chat {chat_id}")
            return wrapped
        else:
            msg = await self.client.send_video(
                chat_id, video, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.debug(f"🎥 Video sent to chat {chat_id}")
            return wrapped

    async def get_chat(self, chat_id):
        if self.platform == "telegram":
            chat = await self.client.get_entity(chat_id)
            return type('Chat', (), {
                'id': chat.id,
                'title': getattr(chat, 'title', None),
                'username': getattr(chat, 'username', None),
                'type': 'private' if isinstance(chat, types.User) else 'group' if isinstance(chat, (types.Chat, types.Channel)) and not getattr(chat, 'broadcast', False) else 'channel'
            })
        else:
            return await self.client.get_chat(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        if self.platform == "telegram":
            try:
                participant = await self.client.get_participant(chat_id, user_id)
                
                status = "member"
                if isinstance(participant, types.ChannelParticipantAdmin):
                    status = "administrator"
                elif isinstance(participant, types.ChannelParticipantCreator):
                    status = "creator"
                elif isinstance(participant, types.ChannelParticipant):
                    status = "member"
                elif isinstance(participant, types.ChatParticipantAdmin):
                    status = "administrator"
                elif isinstance(participant, types.ChatParticipantCreator):
                    status = "creator"
                elif isinstance(participant, types.ChatParticipant):
                    status = "member"
                else:
                    status = "left"
                
                user = participant.user if hasattr(participant, 'user') else await self.client.get_entity(user_id)
                
                return type('ChatMember', (), {
                    'user': type('User', (), {
                        'id': user.id,
                        'is_bot': getattr(user, 'bot', False),
                        'username': getattr(user, 'username', None),
                        'first_name': getattr(user, 'first_name', None)
                    }),
                    'status': status,
                    'is_member': status != "left"
                })
            except Exception:
                return type('ChatMember', (), {
                    'user': type('User', (), {
                        'id': user_id,
                        'is_bot': False,
                        'username': None,
                        'first_name': None
                    }),
                    'status': "left",
                    'is_member': False
                })
        else:
            member = await self.client.get_chat_member(chat_id, user_id)
            return member

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        if self.platform == "telegram":
            await self.client(functions.messages.SetBotCallbackAnswerRequest(
                query_id=int(callback_query_id),
                message=text,
                alert=show_alert
            ))
            logger.debug(f"✅ Callback query {callback_query_id} answered: {text}")
        else:
            await self.client.answer_callback_query(callback_query_id, text, show_alert)
            logger.debug(f"✅ Callback query {callback_query_id} answered: {text}")

    async def send_chat_action(self, chat_id, action):
        if self.platform == "telegram":
            tg_action = {
                "typing": types.SendMessageTypingAction(),
                "upload_photo": types.SendMessageUploadPhotoAction(),
                "record_audio": types.SendMessageRecordAudioAction(),
                "upload_audio": types.SendMessageUploadAudioAction(),
                "record_video": types.SendMessageRecordVideoAction(),
                "upload_video": types.SendMessageUploadVideoAction(),
                "upload_document": types.SendMessageUploadDocumentAction(),
                "find_location": types.SendMessageGeoLocationAction(),
                "record_video_note": types.SendMessageRecordRoundAction(),
                "upload_video_note": types.SendMessageUploadRoundAction(),
            }.get(action, types.SendMessageTypingAction())
            
            await self.client(functions.messages.SetTypingRequest(
                peer=chat_id,
                action=tg_action
            ))
            logger.debug(f"⌨️ Chat action '{action}' sent to {chat_id}")
        else:
            await self.client.send_chat_action(chat_id, action)
            logger.debug(f"⌨️ Chat action '{action}' sent to {chat_id}")

    async def get_me(self):
        if self.platform == "telegram":
            if hasattr(self, '_tg_me'):
                return self._tg_me
            return await self.client.get_me()
        else:
            return self.client.user

    async def download_media(self, message, file_path=None):
        if self.platform == "telegram":
            result = await self.client.download_media(message.raw, file=file_path)
            logger.debug(f"💾 Media downloaded to {result}")
            return result
        else:
            if hasattr(message, 'photo') and message.photo:
                result = await self.client.download_photo(message.photo, file_path)
                logger.debug(f"💾 Photo downloaded to {result}")
                return result
            elif hasattr(message, 'document') and message.document:
                result = await self.client.download_document(message.document, file_path)
                logger.debug(f"💾 Document downloaded to {result}")
                return result
            elif hasattr(message, 'audio') and message.audio:
                result = await self.client.download_audio(message.audio, file_path)
                logger.debug(f"💾 Audio downloaded to {result}")
                return result
            elif hasattr(message, 'voice') and message.voice:
                result = await self.client.download_voice(message.voice, file_path)
                logger.debug(f"💾 Voice downloaded to {result}")
                return result
        return None

    def run(self):
        """Run the bot"""
        if self.platform == "telegram":
            # Define async function to run the bot
            async def run_telegram():
                logger.info("🚀 Starting Telegram bot...")
                
                # Start the client with bot token
                await self.client.start(bot_token=BOT_TOKEN)
                self._tg_me = await self.client.get_me()
                
                logger.info(f"✨ Bot information:")
                logger.info(f"   • Username: @{self._tg_me.username}")
                logger.info(f"   • ID: {self._tg_me.id}")
                logger.info(f"   • Name: {self._tg_me.first_name} {getattr(self._tg_me, 'last_name', '')}")
                logger.info(f"📝 Registered handlers:")
                logger.info(f"   • Message handlers: {len(self._message_handlers)}")
                logger.info(f"   • Callback handlers: {len(self._callback_handlers)}")
                logger.info(f"   • Init handlers: {len(self._init_handlers)}")
                logger.info(f"   • Shutdown handlers: {len(self._shutdown_handlers)}")
                
                # Run initialize handlers
                for handler in self._init_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler()
                        else:
                            handler()
                        logger.debug(f"✅ Init handler executed: {handler.__name__}")
                    except Exception as e:
                        logger.error(f"❌ Error in init handler {handler.__name__}: {e}")
                        await self._handle_error(e, {"handler": handler, "event": "init"})
                
                logger.info("✅ Bot is ready and listening for updates...")
                logger.info("💡 Press Ctrl+C to stop the bot")
                
                # Keep the bot running
                await self.client.run_until_disconnected()
            
            # Run the async function
            try:
                self.client.loop.run_until_complete(run_telegram())
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
            except Exception as e:
                logger.error(f"❌ Bot crashed: {e}")
                import traceback
                traceback.print_exc()
                raise
            finally:
                # Run shutdown handlers
                logger.info("🔄 Running shutdown handlers...")
                for handler in self._shutdown_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            self.client.loop.run_until_complete(handler())
                        else:
                            handler()
                        logger.debug(f"✅ Shutdown handler executed: {handler.__name__}")
                    except Exception as e:
                        logger.error(f"❌ Error in shutdown handler {handler.__name__}: {e}")
                logger.info("👋 Bot shutdown complete")
        else:
            # Bale platform
            logger.info("🚀 Starting Bale bot...")
            self.client.run()
