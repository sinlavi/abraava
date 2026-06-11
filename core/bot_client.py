from core.config import PLATFORM, BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, PROXY
from core.logger import logger
import asyncio
from datetime import datetime

if PLATFORM == "telegram":
    from telethon import TelegramClient, events, Button
    import telethon.types as types
    import telethon.functions as functions
else:
    from balethon import Client
    from balethon.objects import InlineKeyboard, InlineKeyboardButton

# ==================== کلاس‌های کمکی ====================
class User:
    """کلاس کاربر بر اساس مستندات Telethon [citation:5]"""
    def __init__(self, user_id: int, first_name: str = None, last_name: str = None, 
                 username: str = None, is_bot: bool = False):
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.is_bot = is_bot
    
    @property
    def full_name(self) -> str:
        """دریافت نام کامل کاربر"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.username or str(self.id)
    
    def __str__(self) -> str:
        return self.full_name

class Chat:
    """کلاس چت بر اساس مستندات Telethon [citation:5]"""
    def __init__(self, chat_id: int, chat_type: str, title: str = None, username: str = None):
        self.id = chat_id
        self.type = chat_type  # 'private', 'group', 'channel', 'supergroup'
        self.title = title
        self.username = username

class WrappedMessage:
    """کلاس wrapper برای پیام‌های Telethon [citation:1][citation:5]"""
    def __init__(self, message, platform: str):
        self.raw = message
        self.platform = platform
        self.client_wrapper = None
        
        if platform == "telegram":
            self.id = message.id
            self.date = message.date
            self.is_outgoing = getattr(message, 'out', False)
            
            # دریافت اطلاعات فرستنده با استفاده از get_sender() [citation:10]
            self._sender = None
            
            # دریافت متن پیام (از attribute message یا caption) [citation:5]
            self.content = getattr(message, 'message', None)
            self.caption = getattr(message, 'caption', None)
            if not self.content and self.caption:
                self.content = self.caption
            
            # دریافت اطلاعات چت
            self.chat = Chat(
                chat_id=message.chat_id,
                chat_type=self._get_chat_type(message),
                title=getattr(message.chat, 'title', None) if hasattr(message, 'chat') else None,
                username=getattr(message.chat, 'username', None) if hasattr(message, 'chat') else None
            )
            
            # دریافت اطلاعات reply_to [citation:5]
            self.reply_to_message = None
            if hasattr(message, 'reply_to') and message.reply_to:
                self.reply_to_message = type('Reply', (), {
                    'id': message.reply_to.reply_to_msg_id,
                    'sender_id': None
                })
            
            # مدیریت مدیا [citation:5]
            self.photo = None
            self.document = None
            self.audio = None
            self.voice = None
            self.video = None
            self.animation = None
            self.sticker = None
            self.media_type = "text"
            self.file_name = None
            
            if hasattr(message, 'photo') and message.photo:
                self.photo = message.photo
                self.media_type = "photo"
            elif hasattr(message, 'document') and message.document:
                self.document = message.document
                self.media_type = "document"
                self.file_name = getattr(message.document, 'attributes', [{}])[0].get('file_name') if message.document.attributes else None
                
                # بررسی نوع سند [citation:5]
                for attr in message.document.attributes:
                    if isinstance(attr, types.DocumentAttributeAudio):
                        self.audio = message.document
                        self.media_type = "audio" if not getattr(attr, 'voice', False) else "voice"
                        break
                    elif isinstance(attr, types.DocumentAttributeVideo):
                        self.video = message.document
                        self.media_type = "video"
                        break
                    elif isinstance(attr, types.DocumentAttributeSticker):
                        self.sticker = message.document
                        self.media_type = "sticker"
                        break
                    elif isinstance(attr, types.DocumentAttributeAnimated):
                        self.animation = message.document
                        self.media_type = "animation"
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
            self.content = getattr(message, 'content', None)
            self.caption = getattr(message, 'caption', None)
            self._sender = getattr(message, 'author', None)
            self.reply_to_message = getattr(message, 'reply_to_message', None)
            
            # Bale chat info
            bale_chat = getattr(message, 'chat', None)
            self.chat = Chat(
                chat_id=getattr(bale_chat, 'id', 0),
                chat_type=getattr(bale_chat, 'type', 'unknown'),
                title=getattr(bale_chat, 'title', None),
                username=None
            )
            
            # Bale media
            self.photo = getattr(message, 'photo', None)
            self.document = getattr(message, 'document', None)
            self.audio = getattr(message, 'audio', None)
            self.voice = getattr(message, 'voice', None)
            self.video = getattr(message, 'video', None)
            self.media_type = getattr(message, 'media_type', 'text')
    
    def _get_chat_type(self, message) -> str:
        """دریافت نوع چت [citation:5]"""
        if hasattr(message, 'is_private') and message.is_private:
            return 'private'
        elif hasattr(message, 'is_group') and message.is_group:
            return 'group'
        elif hasattr(message, 'is_channel') and message.is_channel:
            return 'channel'
        return 'unknown'
    
    async def get_sender(self) -> User:
        """دریافت اطلاعات فرستنده [citation:10]"""
        if self.platform != "telegram":
            return self._sender
        
        if self._sender is None:
            try:
                sender_entity = await self.raw.get_sender()
                if sender_entity:
                    self._sender = User(
                        user_id=getattr(sender_entity, 'id', self.raw.sender_id),
                        first_name=getattr(sender_entity, 'first_name', None),
                        last_name=getattr(sender_entity, 'last_name', None),
                        username=getattr(sender_entity, 'username', None),
                        is_bot=getattr(sender_entity, 'bot', False)
                    )
                else:
                    self._sender = User(user_id=self.raw.sender_id)
            except Exception as e:
                logger.warning(f"Could not get sender: {e}")
                self._sender = User(user_id=self.raw.sender_id)
        
        return self._sender
    
    @property
    def author(self) -> User:
        """دسترسی همزمان به فرستنده (نیاز به await دارد - برای compatibility)"""
        return self._sender
    
    async def reply(self, text: str, reply_markup=None) -> 'WrappedMessage':
        """پاسخ به پیام [citation:4]"""
        return await self.client_wrapper.send_message(
            self.chat.id, text,
            reply_markup=reply_markup,
            reply_to_message_id=self.id
        )
    
    async def edit(self, text: str, reply_markup=None) -> 'WrappedMessage':
        """ویرایش پیام"""
        return await self.client_wrapper.edit_message(
            self.chat.id, self.id, text, reply_markup=reply_markup
        )
    
    async def delete(self):
        """حذف پیام"""
        return await self.client_wrapper.delete_message(self.chat.id, self.id)
    
    async def download_media(self, file_path: str = None) -> str:
        """دانلود مدیا [citation:4]"""
        if not self.has_media:
            return None
        if self.platform == "telegram":
            return await self.client_wrapper.client.download_media(self.raw, file=file_path)
        # Bale download logic
        return None
    
    @property
    def has_media(self) -> bool:
        """بررسی وجود مدیا"""
        return any([self.photo, self.document, self.audio, self.voice, self.video, self.animation, self.sticker])
    
    @property
    def message_link(self) -> str:
        """لینک پیام (فقط تلگرام) [citation:5]"""
        if self.platform == "telegram" and self.chat.type in ['channel', 'supergroup']:
            if self.chat.username:
                return f"https://t.me/{self.chat.username}/{self.id}"
            else:
                chat_id = str(self.chat.id)
                if chat_id.startswith('-100'):
                    chat_id = chat_id[4:]
                return f"https://t.me/c/{chat_id}/{self.id}"
        return None

class WrappedCallbackQuery:
    """کلاس wrapper برای CallbackQuery [citation:5]"""
    def __init__(self, query, platform: str):
        self.raw = query
        self.platform = platform
        
        if platform == "telegram":
            self.id = query.id
            self.sender_id = query.sender_id
            self.data = query.data.decode() if isinstance(query.data, bytes) else query.data
            self.message = WrappedMessage(query.message, platform) if query.message else None
            self.chat_instance = query.chat_instance
        else:
            self.id = query.id
            self.sender_id = getattr(query, 'author', None)
            self.data = query.data
            self.message = WrappedMessage(query.message, platform) if query.message else None
    
    async def answer(self, text: str = None, show_alert: bool = False, url: str = None):
        """پاسخ به CallbackQuery [citation:5]"""
        if self.platform == "telegram":
            await self.raw.answer(message=text, alert=show_alert, url=url)
        else:
            await self.client_wrapper.answer_callback_query(self.id, text, show_alert)
    
    async def edit_message(self, text: str, reply_markup=None):
        """ویرایش پیام مربوط به این Callback"""
        if self.message:
            return await self.message.edit(text, reply_markup)
        return None

# ==================== کلاس اصلی BotClient ====================
class BotClient:
    """کلاس اصلی ربات با پشتیبانی از Telethon و Balethon"""
    
    def __init__(self):
        self.platform = PLATFORM
        self.proxy = PROXY
        self._message_handlers = []
        self._callback_handlers = []
        self._init_handlers = []
        self._shutdown_handlers = []
        self._error_handlers = []
        
        if PLATFORM == "telegram":
            # تنظیم پراکسی [citation:4]
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
            
            # ثبت event handlers [citation:4]
            @self.client.on(events.NewMessage)
            async def message_handler(event):
                await self._on_telegram_message(event)
            
            @self.client.on(events.CallbackQuery)
            async def callback_handler(event):
                await self._on_telegram_callback(event)
        
        else:  # Balethon
            self.client = Client(token=BOT_TOKEN, proxy=PROXY)
            self.client.on_message()(self._on_bale_message)
            self.client.on_callback_query()(self._on_bale_callback)
            self.client.on_initialize()(self._on_bale_init)
            self.client.on_shutdown()(self._on_bale_shutdown)
    
    # ==================== Event Handlers ====================
    async def _on_telegram_message(self, event):
        """مدیریت پیام‌های تلگرام [citation:1][citation:5]"""
        try:
            message = event.message
            
            # دریافت اطلاعات فرستنده
            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', 'Unknown') if sender else 'Unknown'
            
            logger.info(f"📩 New message from {sender_name} (ID: {message.sender_id}) "
                       f"in chat {message.chat_id}: {getattr(message, 'message', '')}")
            
            wrapped = WrappedMessage(message, "telegram")
            wrapped.client_wrapper = self
            
            for handler in self._message_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler.__name__, "message": wrapped})
        except Exception as e:
            await self._handle_error(e, {"event": "telegram_message"})
    
    async def _on_telegram_callback(self, event):
        """مدیریت CallbackQuery تلگرام [citation:5]"""
        try:
            logger.info(f"🔘 Callback received: {event.data}")
            wrapped = WrappedCallbackQuery(event, "telegram")
            wrapped.client_wrapper = self
            
            for handler in self._callback_handlers:
                try:
                    await handler(wrapped)
                except Exception as e:
                    await self._handle_error(e, {"handler": handler.__name__, "callback": wrapped})
        except Exception as e:
            await self._handle_error(e, {"event": "telegram_callback"})
    
    async def _on_bale_message(self, message):
        """مدیریت پیام‌های بیل"""
        try:
            wrapped = WrappedMessage(message, "bale")
            wrapped.client_wrapper = self
            for handler in self._message_handlers:
                await handler(wrapped)
        except Exception as e:
            await self._handle_error(e, {"event": "bale_message"})
    
    async def _on_bale_callback(self, callback_query):
        """مدیریت CallbackQuery بیل"""
        try:
            wrapped = WrappedCallbackQuery(callback_query, "bale")
            wrapped.client_wrapper = self
            for handler in self._callback_handlers:
                await handler(wrapped)
        except Exception as e:
            await self._handle_error(e, {"event": "bale_callback"})
    
    async def _on_bale_init(self):
        for handler in self._init_handlers:
            await handler()
    
    async def _on_bale_shutdown(self):
        for handler in self._shutdown_handlers:
            await handler()
    
    async def _handle_error(self, error, context=None):
        for handler in self._error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error, context)
                else:
                    handler(error, context)
            except Exception as e:
                logger.error(f"Error in error handler: {e}")
    
    # ==================== Decorators ====================
    def on_message(self):
        """دکوراتور برای ثبت هندلر پیام"""
        def decorator(handler):
            self._message_handlers.append(handler)
            logger.info(f"✅ Message handler registered: {handler.__name__}")
            return handler
        return decorator
    
    def on_callback_query(self):
        """دکوراتور برای ثبت هندلر CallbackQuery"""
        def decorator(handler):
            self._callback_handlers.append(handler)
            logger.info(f"✅ Callback handler registered: {handler.__name__}")
            return handler
        return decorator
    
    def on_initialize(self):
        """دکوراتور برای ثبت هندلر استارت"""
        def decorator(handler):
            self._init_handlers.append(handler)
            return handler
        return decorator
    
    def on_shutdown(self):
        """دکوراتور برای ثبت هندلر خاموشی"""
        def decorator(handler):
            self._shutdown_handlers.append(handler)
            return handler
        return decorator
    
    def on_error(self):
        """دکوراتور برای ثبت هندلر خطا"""
        def decorator(handler):
            self._error_handlers.append(handler)
            return handler
        return decorator
    
    # ==================== Properties ====================
    @property
    def user(self):
        """دریافت اطلاعات ربات [citation:4]"""
        if self.platform == "telegram":
            if hasattr(self, '_tg_me'):
                return User(
                    user_id=self._tg_me.id,
                    first_name=self._tg_me.first_name,
                    last_name=getattr(self._tg_me, 'last_name', None),
                    username=self._tg_me.username,
                    is_bot=getattr(self._tg_me, 'bot', True)
                )
            return None
        return self.client.user
    
    # ==================== Keyboard Helpers ====================
    def _convert_keyboard(self, keyboard):
        """تبدیل کیبورد به فرمت مناسب هر پلتفرم [citation:4]"""
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
    
    # ==================== Send Methods ====================
    async def send_message(self, chat_id, text: str, reply_markup=None, 
                          reply_to_message_id: int = None, parse_mode: str = 'md') -> WrappedMessage:
        """ارسال پیام متنی [citation:1][citation:4]"""
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
            return wrapped
        else:
            msg = await self.client.send_message(chat_id, text, reply_markup=markup, 
                                                  reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped
    
    async def edit_message(self, chat_id, message_id: int, text: str, 
                          reply_markup=None, parse_mode: str = 'md') -> WrappedMessage:
        """ویرایش پیام [citation:4]"""
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
                    return wrapped
                return None
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return None
                raise
        else:
            try:
                msg = await self.client.edit_message_text(chat_id, message_id, text, reply_markup=markup)
                wrapped = WrappedMessage(msg, "bale")
                wrapped.client_wrapper = self
                return wrapped
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return None
                raise
    
    async def delete_message(self, chat_id, message_id: int):
        """حذف پیام"""
        if self.platform == "telegram":
            await self.client.delete_messages(chat_id, [message_id])
        else:
            await self.client.delete_message(chat_id, message_id)
    
    async def send_photo(self, chat_id, photo, caption: str = None, 
                        reply_markup=None, reply_to_message_id: int = None) -> WrappedMessage:
        """ارسال عکس"""
        markup = self._convert_keyboard(reply_markup)
        
        if self.platform == "telegram":
            msg = await self.client.send_file(
                chat_id, photo, caption=caption,
                buttons=markup, reply_to=reply_to_message_id
            )
            wrapped = WrappedMessage(msg, "telegram")
            wrapped.client_wrapper = self
            return wrapped
        else:
            msg = await self.client.send_photo(chat_id, photo, caption=caption,
                                                reply_markup=markup, reply_to_message_id=reply_to_message_id)
            wrapped = WrappedMessage(msg, "bale")
            wrapped.client_wrapper = self
            return wrapped
    
    async def get_chat(self, chat_id):
        """دریافت اطلاعات چت [citation:4]"""
        if self.platform == "telegram":
            chat = await self.client.get_entity(chat_id)
            return Chat(
                chat_id=chat.id,
                chat_type='private' if isinstance(chat, types.User) else 'group',
                title=getattr(chat, 'title', None),
                username=getattr(chat, 'username', None)
            )
        return await self.client.get_chat(chat_id)
    
    async def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        """پاسخ به CallbackQuery [citation:5]"""
        if self.platform == "telegram":
            await self.client(functions.messages.SetBotCallbackAnswerRequest(
                query_id=int(callback_query_id),
                message=text,
                alert=show_alert
            ))
        else:
            await self.client.answer_callback_query(callback_query_id, text, show_alert)
    
    async def send_chat_action(self, chat_id, action: str):
        """ارسال اکشن چت [citation:4]"""
        if self.platform == "telegram":
            tg_action = {
                "typing": types.SendMessageTypingAction(),
                "upload_photo": types.SendMessageUploadPhotoAction(),
                "record_audio": types.SendMessageRecordAudioAction(),
                "upload_audio": types.SendMessageUploadAudioAction(),
                "record_video": types.SendMessageRecordVideoAction(),
                "upload_video": types.SendMessageUploadVideoAction(),
                "upload_document": types.SendMessageUploadDocumentAction(),
            }.get(action, types.SendMessageTypingAction())
            
            await self.client(functions.messages.SetTypingRequest(
                peer=chat_id, action=tg_action
            ))
        else:
            await self.client.send_chat_action(chat_id, action)
    
    # ==================== Run Method ====================
    def run(self):
        """اجرای ربات"""
        if self.platform == "telegram":
            async def start_bot():
                logger.info("🚀 Starting Telegram bot...")
                await self.client.start(bot_token=BOT_TOKEN)
                self._tg_me = await self.client.get_me()
                
                logger.info(f"✨ Bot: @{self._tg_me.username} (ID: {self._tg_me.id})")
                logger.info(f"📝 Handlers: Message={len(self._message_handlers)}, "
                           f"Callback={len(self._callback_handlers)}")
                
                for handler in self._init_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler()
                        else:
                            handler()
                    except Exception as e:
                        await self._handle_error(e, {"handler": handler.__name__})
                
                logger.info("✅ Bot is ready! Press Ctrl+C to stop.")
                await self.client.run_until_disconnected()
            
            try:
                self.client.loop.run_until_complete(start_bot())
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
            except Exception as e:
                logger.error(f"❌ Bot crashed: {e}")
                import traceback
                traceback.print_exc()
            finally:
                for handler in self._shutdown_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            self.client.loop.run_until_complete(handler())
                        else:
                            handler()
                    except Exception as e:
                        logger.error(f"Error in shutdown: {e}")
        else:
            self.client.run()
