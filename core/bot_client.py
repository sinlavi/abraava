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
        self.client_wrapper = None
        
        if platform == "telegram":
            self.id = message.id
            self.date = getattr(message, 'date', datetime.now())
            self.is_outgoing = getattr(message, 'out', False)
            
            # دریافت اطلاعات فرستنده
            sender = message.sender
            self.author = type('Author', (), {
                'id': message.sender_id,
                'is_bot': getattr(sender, 'bot', False) if sender else False,
                'username': getattr(sender, 'username', None),
                'first_name': getattr(sender, 'first_name', None),
                'last_name': getattr(sender, 'last_name', None) if sender else None
            })
            
            self.chat = type('Chat', (), {
                'id': message.chat_id,
                'type': 'private' if message.is_private else 'group' if message.is_group or message.is_supergroup else 'channel' if message.is_channel else 'unknown',
                'title': getattr(message.chat, 'title', None) if hasattr(message, 'chat') else None,
                'username': getattr(message.chat, 'username', None) if hasattr(message, 'chat') else None
            })
            
            # دریافت متن پیام
            self.content = getattr(message, 'text', None)
            self.caption = getattr(message, 'caption', None)
            if not self.content and self.caption:
                self.content = self.caption
            
            self.reply_to_message = None
            if hasattr(message, 'reply_to') and message.reply_to:
                self.reply_to_message = type('Reply', (), {
                    'id': message.reply_to.reply_to_msg_id,
                    'author': type('Author', (), {'id': None})
                })
            
            # مدیریت مدیا
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
                if self.caption:
                    self.content = self.caption
                    
            elif hasattr(message, 'document') and message.document:
                self.document = message.document
                self.media_type = "document"
                
                for attr in message.document.attributes:
                    if isinstance(attr, types.DocumentAttributeAudio):
                        self.audio = message.document
                        self.media_type = "audio" if not getattr(attr, 'voice', False) else "voice"
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
            self.date = datetime.now()
            self.is_outgoing = False
            self.author = message.author
            self.chat = message.chat
            self.content = getattr(message, 'content', None)
            self.caption = getattr(message, 'caption', None)
            self.reply_to_message = getattr(message, 'reply_to_message', None)
            
            self.photo = getattr(message, 'photo', None)
            self.document = getattr(message, 'document', None)
            self.audio = getattr(message, 'audio', None)
            self.voice = getattr(message, 'voice', None)
            self.video = getattr(message, 'video', None)
            self.animation = getattr(message, 'animation', None)
            self.sticker = getattr(message, 'sticker', None)
            self.media_type = getattr(message, 'media_type', 'text')

    async def reply(self, text, reply_markup=None):
        logger.debug(f"💬 Replying to message {self.id}")
        return await self.client_wrapper.send_message(
            self.chat.id, text, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def reply_photo(self, photo, caption=None, reply_markup=None):
        logger.debug(f"📸 Replying with photo to message {self.id}")
        return await self.client_wrapper.send_photo(
            self.chat.id, photo, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def reply_audio(self, audio, caption=None, reply_markup=None, **kwargs):
        logger.debug(f"🎵 Replying with audio to message {self.id}")
        return await self.client_wrapper.send_audio(
            self.chat.id, audio, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id, 
            **kwargs
        )

    async def reply_voice(self, voice, caption=None, reply_markup=None):
        logger.debug(f"🎤 Replying with voice to message {self.id}")
        return await self.client_wrapper.send_voice(
            self.chat.id, voice, 
            caption=caption, 
            reply_markup=reply_markup, 
            reply_to_message_id=self.id
        )

    async def edit(self, text, reply_markup=None):
        logger.debug(f"✏️ Editing message {self.id}")
        return await self.client_wrapper.edit_message(
            self.chat.id, self.id, 
            text, 
            reply_markup=reply_markup
        )

    async def delete(self):
        logger.debug(f"🗑️ Deleting message {self.id}")
        return await self.client_wrapper.delete_message(self.chat.id, self.id)
    
    async def download_media(self, file_path=None):
        if not self.has_media:
            logger.warning(f"⚠️ No media to download in message {self.id}")
            return None
            
        logger.info(f"💾 Downloading media from message {self.id}")
        if self.platform == "telegram":
            result = await self.client_wrapper.client.download_media(self.raw, file=file_path)
            logger.info(f"✅ Media downloaded to: {result}")
            return result
        else:
            if self.photo:
                result = await self.client_wrapper.client.download_photo(self.photo, file_path)
            elif self.document:
                result = await self.client_wrapper.client.download_document(self.document, file_path)
            elif self.audio:
                result = await self.client_wrapper.client.download_audio(self.audio, file_path)
            elif self.voice:
                result = await self.client_wrapper.client.download_voice(self.voice, file_path)
            elif self.video:
                result = await self.client_wrapper.client.download_video(self.video, file_path)
            else:
                return None
            logger.info(f"✅ Media downloaded to: {result}")
            return result
    
    @property
    def has_media(self):
        return any([
            self.photo, self.document, self.audio, 
            self.voice, self.video, self.animation, 
            self.sticker
        ])
    
    @property
    def file_id(self):
        if self.platform == "telegram":
            media = self.photo or self.document or self.audio or self.voice or self.video or self.animation or self.sticker
            if media:
                try:
                    return utils.pack_bot_file_id(media)
                except Exception:
                    return None
            return None
        else:
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
            if self.chat.type in ["channel", "supergroup"]:
                if hasattr(self.chat, 'username') and self.chat.username:
                    return f"https://t.me/{self.chat.username}/{self.id}"
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
        self.client_wrapper = None
        
        if platform == "telegram":
            self.id = query.id
            self.sender_id = query.sender_id
            self.data = query.data.decode() if isinstance(query.data, bytes) else query.data
            self.chat_instance = getattr(query, 'chat_instance', None)
            
            if hasattr(query, 'message') and query.message is not None:
                self.message = WrappedMessage(query.message, platform)
                if self.message:
                    self.message.client_wrapper = self.client_wrapper
                logger.debug(f"🔘 Callback {self.id} has associated message: {self.message.id}")
            else:
                self.message = None
                logger.warning(f"⚠️ Callback {self.id} has no associated message")
                
            self.author = type('Author', (), {
                'id': query.sender_id,
                'first_name': None,
                'last_name': None,
                'username': None,
                'is_bot': False
            })
        else:
            self.id = query.id
            self.author = query.author
            self.data = query.data
            if hasattr(query, 'message') and query.message:
                self.message = WrappedMessage(query.message, platform)
            else:
                self.message = None

    async def answer(self, text=None, show_alert=False):
        logger.debug(f"🔘 Answering callback {self.id}")
        return await self.client_wrapper.answer_callback_query(self.id, text, show_alert)
    
    async def edit_message(self, text, reply_markup=None):
        if self.message is not None and hasattr(self.message, 'chat') and self.message.chat:
            logger.debug(f"✏️ Editing message {self.message.id} from callback {self.id}")
            return await self.message.edit(text, reply_markup)
        logger.warning(f"⚠️ Cannot edit message for callback {self.id}")
        return None
    
    async def delete_message(self):
        if self.message is not None and hasattr(self.message, 'chat') and self.message.chat:
            logger.debug(f"🗑️ Deleting message {self.message.id} from callback {self.id}")
            return await self.message.delete()
        logger.warning(f"⚠️ Cannot delete message for callback {self.id}")
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

        if PLATFORM == "telegram":
            # تنظیم پراکسی - فقط در صورت وجود پراکسی معتبر
            self.proxy_config = None
            if PROXY and PROXY.strip():
                try:
                    import socks
                    # پشتیبانی از فرمت‌های مختلف پراکسی
                    proxy_url = PROXY.strip()
                    
                    # حذف پروتکل
                    if proxy_url.startswith("socks5h://"):
                        proxy_url = proxy_url[9:]
                    elif proxy_url.startswith("socks5://"):
                        proxy_url = proxy_url[8:]
                    elif proxy_url.startswith("socks4://"):
                        proxy_url = proxy_url[8:]
                    
                    # جدا کردن اطلاعات احراز هویت
                    username = None
                    password = None
                    
                    if "@" in proxy_url:
                        auth, addr = proxy_url.split("@")
                        if ":" in auth:
                            username, password = auth.split(":")
                        else:
                            username = auth
                        host, port = addr.split(":")
                    else:
                        host, port = proxy_url.split(":")
                    
                    # ساخت تنظیمات پراکسی
                    self.proxy_config = (socks.SOCKS5, host, int(port), True, username, password)
                    logger.info(f"🔌 Proxy configured: {host}:{port}")
                except Exception as e:
                    logger.warning(f"⚠️ Invalid proxy configuration: {e}")
                    self.proxy_config = None
            else:
                logger.info("🔌 No proxy configured, using direct connection")
            
            # ایجاد کلاینت تلگرام
            self.client = TelegramClient(
                "abraava_tg", 
                int(TELEGRAM_API_ID), 
                TELEGRAM_API_HASH, 
                proxy=self.proxy_config,
                connection_retries=5,
                retry_delay=1
            )
            
            @self.client.on(events.NewMessage(incoming=True))
            async def handler_message(event):
                await self._tg_on_message(event)
            
            @self.client.on(events.CallbackQuery())
            async def handler_callback(event):
                await self._tg_on_callback(event)
            
            logger.info("🤖 Telegram bot client initialized")
                
        else:
            self.client = Client(token=BOT_TOKEN, proxy=PROXY if PROXY else None)
            self.client.on_message()(self._bale_on_message)
            self.client.on_callback_query()(self._bale_on_callback)
            self.client.on_initialize()(self._bale_on_init)
            self.client.on_shutdown()(self._bale_on_shutdown)
            logger.info("🤖 Bale bot client initialized")

    async def _handle_error(self, error, context=None):
        logger.error(f"❌ Error occurred: {error}")
        if context:
            logger.error(f"📋 Context: {context}")
        
        for handler in self._error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error, context)
                else:
                    handler(error, context)
                logger.debug(f"✅ Error handled by {handler.__name__}")
            except Exception as e:
                logger.error(f"❌ Error in error handler {handler.__name__}: {e}")

    async def _tg_on_message(self, event):
        try:
            sender = await event.get_sender()
            sender_name = getattr(sender, 'first_name', 'Unknown') if sender else 'Unknown'
            message_text = getattr(event.message, 'text', None) or getattr(event.message, 'caption', None)
            
            logger.info(f"📩 [TELEGRAM] New message:")
            logger.info(f"   ├─ From: {sender_name} (ID: {event.sender_id})")
            logger.info(f"   ├─ Chat: {event.chat_id}")
            logger.info(f"   ├─ Message ID: {event.message.id}")
            logger.info(f"   ├─ Content: {message_text if message_text else '[EMPTY]'}")
            logger.info(f"   └─ Has Media: {bool(event.message.media)}")
            
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
                    await self._handle_error(e, {"handler": handler.__name__})
                    
        except Exception as e:
            logger.error(f"❌ Critical error in _tg_on_message: {e}")
            import traceback
            traceback.print_exc()
            await self._handle_error(e, {"event": "message"})

    async def _tg_on_callback(self, event):
        try:
            logger.info(f"🔘 [TELEGRAM] Callback query received:")
            logger.info(f"   ├─ ID: {event.id}")
            logger.info(f"   ├─ Sender: {event.sender_id}")
            logger.info(f"   ├─ Data: {event.data}")
            logger.info(f"   └─ Chat Instance: {getattr(event, 'chat_instance', 'N/A')}")
            
            wrapped = WrappedCallbackQuery(event, "telegram")
            wrapped.client_wrapper = self
            
            if wrapped.message is None:
                logger.warning("⚠️ Callback has no associated message")
                await wrapped.answer("عملیات انجام شد")
                return
            
            if not self._callback_handlers:
                logger.warning("⚠️ No callback handlers registered!")
                await wrapped.answer("هیچ هندلری ثبت نشده است")
                return
            
            for handler in self._callback_handlers:
                try:
                    await handler(wrapped)
                    logger.debug(f"✅ Callback handled by {handler.__name__}")
                except Exception as e:
                    logger.error(f"❌ Error in callback handler {handler.__name__}: {e}")
                    await self._handle_error(e, {"handler": handler.__name__})
                    
        except Exception as e:
            logger.error(f"❌ Critical error in _tg_on_callback: {e}")
            import traceback
            traceback.print_exc()
            await self._handle_error(e, {"event": "callback"})

    async def _bale_on_message(self, message):
        try:
            sender_name = message.author.first_name if hasattr(message.author, 'first_name') else str(message.author.id)
            
            logger.info(f"📩 [BALE] New message:")
            logger.info(f"   ├─ From: {sender_name} (ID: {message.author.id})")
            logger.info(f"   ├─ Chat: {message.chat.id}")
            logger.info(f"   ├─ Message ID: {message.id}")
            logger.info(f"   └─ Content: {message.content if message.content else '[EMPTY]'}")
            
            wrapped = WrappedMessage(message, "bale")
            wrapped.client_wrapper = self
            
            for handler in self._message_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler})
        except Exception as e:
            await self._handle_error(e, {"event": "message"})

    async def _bale_on_callback(self, callback_query):
        try:
            logger.info(f"🔘 [BALE] Callback query received:")
            logger.info(f"   ├─ ID: {callback_query.id}")
            logger.info(f"   ├─ Author: {callback_query.author.id}")
            logger.info(f"   └─ Data: {callback_query.data}")
            
            wrapped = WrappedCallbackQuery(callback_query, "bale")
            wrapped.client_wrapper = self
            if wrapped.message:
                wrapped.message.client_wrapper = self
            for handler in self._callback_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler})
        except Exception as e:
            await self._handle_error(e, {"event": "callback"})

    async def _bale_on_init(self):
        logger.info("🚀 Bale bot initializing...")
        for handler in self._init_handlers:
            try:
                await handler()
            except Exception as e:
                await self._handle_error(e, {"handler": handler})
        logger.info("✅ Bale bot initialization complete")

    async def _bale_on_shutdown(self):
        logger.info("🛑 Bale bot shutting down...")
        for handler in self._shutdown_handlers:
            try:
                await handler()
            except Exception as e:
                await self._handle_error(e, {"handler": handler})
        logger.info("✅ Bale bot shutdown complete")

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
            logger.info(f"✅ Init handler registered: {handler.__name__}")
            return handler
        return decorator

    def on_shutdown(self):
        def decorator(handler):
            self._shutdown_handlers.append(handler)
            logger.info(f"✅ Shutdown handler registered: {handler.__name__}")
            return handler
        return decorator
    
    def on_error(self):
        def decorator(handler):
            self._error_handlers.append(handler)
            logger.info(f"✅ Error handler registered: {handler.__name__}")
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
            logger.info("🚀 Starting Telegram bot...")
            try:
                await self.client.start(bot_token=BOT_TOKEN)
                self._tg_me = await self.client.get_me()
                logger.info(f"✨ Bot started as @{self._tg_me.username} (ID: {self._tg_me.id})")
                
                for handler in self._init_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler()
                        else:
                            handler()
                        logger.debug(f"✅ Init handler executed: {handler.__name__}")
                    except Exception as e:
                        await self._handle_error(e, {"handler": handler})
            except Exception as e:
                logger.error(f"❌ Failed to start bot: {e}")
                raise
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
            from utils.helpers import format_markdown
            text = format_markdown(text)
            logger.debug(f"📤 Sending message to {chat_id}: {text[:50]}...")
            result = await self.client.send_message(
                chat_id, text, 
                buttons=markup, 
                reply_to=reply_to_message_id, 
                parse_mode=parse_mode
            )
            wrapped = WrappedMessage(result, "telegram")
            wrapped.client_wrapper = self
            logger.info(f"✅ Message sent to {chat_id} (ID: {result.id})")
            return wrapped
        else:
            logger.debug(f"📤 Sending message to {chat_id}: {text[:50]}...")
            msg = await self.client.send_message(
                chat_id, text, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Message sent to {chat_id} (ID: {msg.id})")
            return wrapped

    async def edit_message(self, chat_id, message_id, text, reply_markup=None, parse_mode='md'):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            text = format_markdown(text)
            try:
                logger.debug(f"✏️ Editing message {message_id} in chat {chat_id}")
                msg = await self.client.edit_message(
                    chat_id, message_id, text, 
                    buttons=markup, 
                    parse_mode=parse_mode
                )
                if msg:
                    wrapped = WrappedMessage(msg, "telegram")
                    wrapped.client_wrapper = self
                    logger.info(f"✅ Message {message_id} edited successfully")
                    return wrapped
                return None
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return None
                raise
        else:
            try:
                logger.debug(f"✏️ Editing message {message_id} in chat {chat_id}")
                msg = await self.client.edit_message_text(
                    chat_id, message_id, text, 
                    reply_markup=markup
                )
                wrapped = WrappedMessage(msg, "bale")
                wrapped.client_wrapper = self
                logger.info(f"✅ Message {message_id} edited successfully")
                return wrapped
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return None
                raise

    async def delete_message(self, chat_id, message_id):
        if self.platform == "telegram":
            logger.debug(f"🗑️ Deleting message {message_id} from chat {chat_id}")
            await self.client.delete_messages(chat_id, [message_id])
            logger.info(f"✅ Message {message_id} deleted")
        else:
            logger.debug(f"🗑️ Deleting message {message_id} from chat {chat_id}")
            await self.client.delete_message(chat_id, message_id)
            logger.info(f"✅ Message {message_id} deleted")

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            caption = format_markdown(caption)
            logger.debug(f"📸 Sending photo to chat {chat_id}")
            msg = await self.client.send_file(
                chat_id, photo, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.info(f"✅ Photo sent to chat {chat_id}")
            return wrapped
        else:
            logger.debug(f"📸 Sending photo to chat {chat_id}")
            msg = await self.client.send_photo(
                chat_id, photo, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Photo sent to chat {chat_id}")
            return wrapped

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, reply_to_message_id=None, **kwargs):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            caption = format_markdown(caption)
            attributes = [types.DocumentAttributeAudio(
                duration=int(kwargs.get('duration', 0)),
                title=kwargs.get('title'),
                performer=kwargs.get('performer')
            )]
            thumb = kwargs.get('thumb')
            logger.debug(f"🎵 Sending audio to chat {chat_id}")
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
            logger.info(f"✅ Audio sent to chat {chat_id}")
            return wrapped
        else:
            logger.debug(f"🎵 Sending audio to chat {chat_id}")
            msg = await self.client.send_audio(
                chat_id, audio, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Audio sent to chat {chat_id}")
            return wrapped

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            caption = format_markdown(caption)
            logger.debug(f"🎤 Sending voice to chat {chat_id}")
            msg = await self.client.send_file(
                chat_id, voice, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id, 
                voice=True
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.info(f"✅ Voice sent to chat {chat_id}")
            return wrapped
        else:
            logger.debug(f"🎤 Sending voice to chat {chat_id}")
            msg = await self.client.send_voice(
                chat_id, voice, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Voice sent to chat {chat_id}")
            return wrapped

    async def send_document(self, chat_id, document, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            caption = format_markdown(caption)
            logger.debug(f"📄 Sending document to chat {chat_id}")
            msg = await self.client.send_file(
                chat_id, document, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.info(f"✅ Document sent to chat {chat_id}")
            return wrapped
        else:
            logger.debug(f"📄 Sending document to chat {chat_id}")
            msg = await self.client.send_document(
                chat_id, document, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Document sent to chat {chat_id}")
            return wrapped

    async def send_video(self, chat_id, video, caption=None, reply_markup=None, reply_to_message_id=None):
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            from utils.helpers import format_markdown
            caption = format_markdown(caption)
            logger.debug(f"🎥 Sending video to chat {chat_id}")
            msg = await self.client.send_file(
                chat_id, video, 
                caption=caption, 
                buttons=markup, 
                reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            logger.info(f"✅ Video sent to chat {chat_id}")
            return wrapped
        else:
            logger.debug(f"🎥 Sending video to chat {chat_id}")
            msg = await self.client.send_video(
                chat_id, video, 
                caption=caption, 
                reply_markup=markup, 
                reply_to_message_id=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            logger.info(f"✅ Video sent to chat {chat_id}")
            return wrapped

    async def get_chat(self, chat_id):
        if self.platform == "telegram":
            logger.debug(f"🔍 Getting chat info for {chat_id}")
            chat = await self.client.get_entity(chat_id)
            chat_info = type('Chat', (), {
                'id': chat.id,
                'title': getattr(chat, 'title', None),
                'username': getattr(chat, 'username', None),
                'type': 'private' if isinstance(chat, types.User) else 'group' if isinstance(chat, (types.Chat, types.Channel)) and not getattr(chat, 'broadcast', False) else 'channel'
            })
            logger.info(f"✅ Chat info retrieved: {chat_info.id}")
            return chat_info
        else:
            return await self.client.get_chat(chat_id)

    async def get_chat_member(self, chat_id, user_id):
        """Get chat member information - Fixed version"""
        if self.platform == "telegram":
            try:
                logger.debug(f"🔍 Getting member {user_id} info from chat {chat_id}")
                
                # Convert chat_id to int if it's numeric
                if isinstance(chat_id, str) and (chat_id.isdigit() or (chat_id.startswith('-') and chat_id[1:].isdigit())):
                    chat_id = int(chat_id)

                # دریافت اطلاعات کاربر و چت
                user = await self.client.get_entity(user_id)
                chat = await self.client.get_entity(chat_id)
                
                # وضعیت پیش‌فرض
                status = "left"
                is_member = False
                
                # برای چت‌های خصوصی، کاربر همیشه عضو است
                if isinstance(chat, types.User):
                    status = "member"
                    is_member = True
                elif isinstance(chat, (types.Chat, types.Channel)):
                    # برای گروه‌ها و کانال‌ها
                    try:
                        if isinstance(chat, types.Channel):
                            # استفاده از GetParticipantRequest برای دقت بیشتر در کانال‌ها
                            try:
                                p = await self.client(functions.channels.GetParticipantRequest(
                                    channel=chat,
                                    participant=user
                                ))
                                participant = p.participant
                                is_member = True
                                if isinstance(participant, types.ChannelParticipantCreator):
                                    status = "creator"
                                elif isinstance(participant, types.ChannelParticipantAdmin):
                                    status = "administrator"
                                else:
                                    status = "member"
                            except Exception as e:
                                if "UserNotParticipantError" in str(e):
                                    is_member = False
                                    status = "left"
                                else:
                                    # Fallback to get_permissions
                                    permissions = await self.client.get_permissions(chat, user)
                                    is_member = permissions.is_member if permissions else False
                                    if is_member:
                                        if permissions.is_admin: status = "administrator"
                                        elif permissions.is_creator: status = "creator"
                                        else: status = "member"
                        else:
                            # گروه‌های معمولی
                            permissions = await self.client.get_permissions(chat, user)
                            is_member = permissions.is_member if permissions else False
                            if is_member:
                                if permissions.is_admin: status = "administrator"
                                elif permissions.is_creator: status = "creator"
                                else: status = "member"
                    except Exception as e:
                        logger.debug(f"Could not get permissions/participant: {e}")
                        status = "unknown"
                        is_member = False
                
                logger.info(f"✅ Member {user_id} status: {status}")
                
                return type('ChatMember', (), {
                    'user': type('User', (), {
                        'id': user.id,
                        'is_bot': getattr(user, 'bot', False),
                        'username': getattr(user, 'username', None),
                        'first_name': getattr(user, 'first_name', None),
                        'last_name': getattr(user, 'last_name', None)
                    }),
                    'status': status,
                    'is_member': is_member
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Could not get member {user_id} in {chat_id}: {e}")
                return type('ChatMember', (), {
                    'user': type('User', (), {
                        'id': user_id,
                        'is_bot': False,
                        'username': None,
                        'first_name': None,
                        'last_name': None
                    }),
                    'status': "unknown",
                    'is_member': False
                })
        else:
            member = await self.client.get_chat_member(chat_id, user_id)
            return member

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        """Answer a callback query - Fixed with cache_time"""
        if self.platform == "telegram":
            logger.debug(f"🔘 Answering callback {callback_query_id}")
            try:
                # Try answering using functions for more control
                await self.client(functions.messages.SetBotCallbackAnswerRequest(
                    query_id=int(callback_query_id),
                    message=text or "",
                    alert=show_alert,
                    cache_time=0
                ))
                logger.info(f"✅ Callback query {callback_query_id} answered")
            except Exception as e:
                logger.error(f"❌ Failed to answer callback {callback_query_id}: {e}")
                # Don't raise, callback answering is not critical
        else:
            await self.client.answer_callback_query(callback_query_id, text, show_alert)
            logger.info(f"✅ Callback query answered")

    async def send_chat_action(self, chat_id, action):
        if self.platform == "telegram":
            tg_action = {
                "typing": types.SendMessageTypingAction(),
                "upload_photo": types.SendMessageUploadPhotoAction(progress=0),
                "record_audio": types.SendMessageRecordAudioAction(),
                "upload_audio": types.SendMessageUploadAudioAction(progress=0),
                "record_video": types.SendMessageRecordVideoAction(),
                "upload_video": types.SendMessageUploadVideoAction(progress=0),
                "upload_document": types.SendMessageUploadDocumentAction(progress=0),
                "find_location": types.SendMessageGeoLocationAction(),
                "record_video_note": types.SendMessageRecordRoundAction(),
                "upload_video_note": types.SendMessageUploadRoundAction(progress=0),
                "cancel": types.SendMessageCancelAction(),
            }.get(action, types.SendMessageTypingAction())
            
            try:
                logger.debug(f"⌨️ Sending chat action '{action}' to {chat_id}")
                await self.client(functions.messages.SetTypingRequest(
                    peer=chat_id,
                    action=tg_action
                ))
                logger.info(f"✅ Chat action '{action}' sent")
            except Exception as e:
                logger.warning(f"⚠️ Could not send chat action: {e}")
        else:
            try:
                await self.client.send_chat_action(chat_id, action)
                logger.info(f"✅ Chat action '{action}' sent")
            except Exception as e:
                logger.warning(f"⚠️ Could not send chat action: {e}")

    async def get_me(self):
        if self.platform == "telegram":
            if hasattr(self, '_tg_me'):
                return self._tg_me
            return await self.client.get_me()
        else:
            return self.client.user

    async def download_media(self, message, file_path=None):
        if self.platform == "telegram":
            logger.debug(f"💾 Downloading media from message {message.id}")
            result = await self.client.download_media(message.raw, file=file_path)
            logger.info(f"✅ Media downloaded: {result}")
            return result
        else:
            if hasattr(message, 'photo') and message.photo:
                result = await self.client.download_photo(message.photo, file_path)
            elif hasattr(message, 'document') and message.document:
                result = await self.client.download_document(message.document, file_path)
            elif hasattr(message, 'audio') and message.audio:
                result = await self.client.download_audio(message.audio, file_path)
            elif hasattr(message, 'voice') and message.voice:
                result = await self.client.download_voice(message.voice, file_path)
            else:
                return None
            logger.info(f"✅ Media downloaded: {result}")
            return result

    def run(self):
        if self.platform == "telegram":
            async def run_telegram():
                logger.info("🚀 Starting Telegram bot...")
                logger.info("=" * 50)
                
                try:
                    await self.client.start(bot_token=BOT_TOKEN)
                except Exception as e:
                    logger.error(f"❌ Failed to connect to Telegram with proxy: {e}")

                    if self.proxy_config:
                        logger.info("🔄 Attempting to connect without proxy...")
                        try:
                            # کلاینت جدید بدون پراکسی
                            self.client = TelegramClient(
                                "abraava_tg_direct",
                                int(TELEGRAM_API_ID),
                                TELEGRAM_API_HASH,
                                proxy=None,
                                connection_retries=5,
                                retry_delay=1
                            )
                            # ثبت مجدد هندلرها برای کلاینت جدید
                            @self.client.on(events.NewMessage(incoming=True))
                            async def handler_message(event):
                                await self._tg_on_message(event)

                            @self.client.on(events.CallbackQuery())
                            async def handler_callback(event):
                                await self._tg_on_callback(event)

                            await self.client.start(bot_token=BOT_TOKEN)
                            logger.info("✅ Connected successfully without proxy")
                        except Exception as e2:
                            logger.error(f"❌ Failed to connect without proxy: {e2}")
                            raise e2
                    else:
                        raise e
                
                self._tg_me = await self.client.get_me()
                
                logger.info(f"✨ Bot Information:")
                logger.info(f"   ├─ Username: @{self._tg_me.username}")
                logger.info(f"   ├─ ID: {self._tg_me.id}")
                logger.info(f"   ├─ Name: {self._tg_me.first_name}")
                logger.info(f"   └─ Is Bot: True")
                
                logger.info(f"📝 Registered Handlers:")
                logger.info(f"   ├─ Message: {len(self._message_handlers)}")
                logger.info(f"   ├─ Callback: {len(self._callback_handlers)}")
                logger.info(f"   ├─ Init: {len(self._init_handlers)}")
                logger.info(f"   └─ Shutdown: {len(self._shutdown_handlers)}")
                
                for handler in self._init_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler()
                        else:
                            handler()
                    except Exception as e:
                        await self._handle_error(e, {"handler": handler})
                
                logger.info("=" * 50)
                logger.info("✅ Bot is ready!")
                logger.info("💡 Press Ctrl+C to stop")
                logger.info("=" * 50)
                
                await self.client.run_until_disconnected()
            
            try:
                self.client.loop.run_until_complete(run_telegram())
            except KeyboardInterrupt:
                logger.info("\n🛑 Bot stopped by user")
            except Exception as e:
                logger.error(f"❌ Bot crashed: {e}")
                import traceback
                traceback.print_exc()
            finally:
                logger.info("🔄 Running shutdown handlers...")
                for handler in self._shutdown_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            self.client.loop.run_until_complete(handler())
                        else:
                            handler()
                    except Exception as e:
                        logger.error(f"Error in shutdown: {e}")
                logger.info("👋 Bot shutdown complete")
        else:
            logger.info("🚀 Starting Bale bot...")
            self.client.run()
