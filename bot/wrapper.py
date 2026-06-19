from abc import ABC, abstractmethod
from typing import Optional, List, Union, Any, Dict
from core.config import PLATFORM

class Message(ABC):
    @property
    @abstractmethod
    def id(self): pass

    @property
    @abstractmethod
    def text(self): pass

    @property
    @abstractmethod
    def chat_id(self): pass

    @property
    @abstractmethod
    def author_id(self): pass

    @property
    @abstractmethod
    def is_group(self): pass

    @property
    @abstractmethod
    def type(self): pass

    @abstractmethod
    async def reply(self, text: str, reply_markup: Any = None): pass

    @abstractmethod
    async def edit(self, text: str, reply_markup: Any = None): pass

    @abstractmethod
    async def delete(self): pass

class CallbackQuery(ABC):
    @property
    @abstractmethod
    def id(self): pass

    @property
    @abstractmethod
    def data(self): pass

    @property
    @abstractmethod
    def message(self) -> Message: pass

    @property
    @abstractmethod
    def author_id(self): pass

    @abstractmethod
    async def answer(self, text: str = None, show_alert: bool = False): pass

class BotClient(ABC):
    @abstractmethod
    async def send_message(self, chat_id: Union[int, str], text: str, reply_markup: Any = None, reply_to_message_id: int = None) -> Message: pass

    @abstractmethod
    async def edit_message(self, chat_id: Union[int, str], message_id: int, text: str, reply_markup: Any = None) -> Message: pass

    @abstractmethod
    async def delete_message(self, chat_id: Union[int, str], message_id: int): pass

    @abstractmethod
    async def send_chat_action(self, chat_id: Union[int, str], action: str): pass

    @abstractmethod
    async def send_audio(self, chat_id: Union[int, str], audio: Any, caption: str = None, reply_markup: Any = None) -> Message: pass

    @abstractmethod
    async def send_voice(self, chat_id: Union[int, str], voice: Any, caption: str = None, reply_markup: Any = None) -> Message: pass

    @abstractmethod
    async def send_photo(self, chat_id: Union[int, str], photo: Any, caption: str = None, reply_markup: Any = None) -> Message: pass

    @abstractmethod
    async def forward_message(self, chat_id: Union[int, str], from_chat_id: Union[int, str], message_id: int) -> Message: pass

    @abstractmethod
    async def get_chat(self, chat_id: Union[int, str]) -> Any: pass

    @abstractmethod
    async def get_chat_member(self, chat_id: Union[int, str], user_id: int) -> Any: pass

    @abstractmethod
    def build_markup(self, buttons: List[List[Dict[str, Any]]]) -> Any: pass

# Balethon Implementation
try:
    from balethon.objects import Message as BaleMessage, CallbackQuery as BaleCallbackQuery, InlineKeyboard, InlineKeyboardButton as BaleInlineKeyboardButton
    class BalethonMessage(Message):
        def __init__(self, message: BaleMessage, client):
            self._msg = message
            self._client = client

        @property
        def id(self): return self._msg.id
        @property
        def text(self): return self._msg.text or self._msg.content or self._msg.caption
        @property
        def chat_id(self): return self._msg.chat.id
        @property
        def author_id(self): return self._msg.author.id if self._msg.author else self._msg.chat.id
        @property
        def is_group(self): return self._msg.chat.type in ["group", "supergroup"]
        @property
        def type(self): return self._msg.chat.type

        async def reply(self, text: str, reply_markup: Any = None):
            return BalethonMessage(await self._msg.reply(text=text, reply_markup=reply_markup), self._client)

        async def edit(self, text: str, reply_markup: Any = None):
            return BalethonMessage(await self._msg.edit(text=text, reply_markup=reply_markup), self._client)

        async def delete(self):
            return await self._msg.delete()

    class BalethonCallbackQuery(CallbackQuery):
        def __init__(self, cq: BaleCallbackQuery, client):
            self._cq = cq
            self._client = client

        @property
        def id(self): return self._cq.id
        @property
        def data(self): return self._cq.data
        @property
        def message(self): return BalethonMessage(self._cq.message, self._client)
        @property
        def author_id(self): return self._cq.author.id

        async def answer(self, text: str = None, show_alert: bool = False):
            return await self._cq.answer(text=text, show_alert=show_alert)

    class BalethonBotClient(BotClient):
        def __init__(self, bot):
            self.bot = bot

        async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
            msg = await self.bot.send_message(chat_id, text=text, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
            return BalethonMessage(msg, self)

        async def edit_message(self, chat_id, message_id, text, reply_markup=None):
            msg = await self.bot.edit_message(chat_id, message_id, text=text, reply_markup=reply_markup)
            return BalethonMessage(msg, self)

        async def delete_message(self, chat_id, message_id):
            return await self.bot.delete_message(chat_id, message_id)

        async def send_chat_action(self, chat_id, action):
            return await self.bot.send_chat_action(chat_id, action)

        async def send_audio(self, chat_id, audio, caption=None, reply_markup=None):
            msg = await self.bot.send_audio(chat_id, audio=audio, caption=caption, reply_markup=reply_markup)
            return BalethonMessage(msg, self)

        async def send_voice(self, chat_id, voice, caption=None, reply_markup=None):
            msg = await self.bot.send_voice(chat_id, voice=voice, caption=caption, reply_markup=reply_markup)
            return BalethonMessage(msg, self)

        async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
            msg = await self.bot.send_photo(chat_id, photo=photo, caption=caption, reply_markup=reply_markup)
            return BalethonMessage(msg, self)

        async def forward_message(self, chat_id, from_chat_id, message_id):
            msg = await self.bot.forward_message(chat_id, from_chat_id, message_id)
            return BalethonMessage(msg, self)

        async def get_chat(self, chat_id):
            return await self.bot.get_chat(chat_id)

        async def get_chat_member(self, chat_id, user_id):
            return await self.bot.get_chat_member(chat_id, user_id)

        def build_markup(self, buttons):
            if not buttons: return None
            bale_rows = []
            for row in buttons:
                bale_row = []
                for btn in row:
                    bale_row.append(BaleInlineKeyboardButton(**btn))
                bale_rows.append(bale_row)
            return InlineKeyboard(*bale_rows)
except ImportError: pass

# Telegram Implementation
try:
    from telegram import Update, InlineKeyboardButton as TGInlineKeyboardButton, InlineKeyboardMarkup, Bot, WebAppInfo
    from telegram.ext import ContextTypes

    class TelegramMessage(Message):
        def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message=None):
            self._update = update
            self._context = context
            self._msg = message or (update.effective_message if update else None)

        @property
        def id(self): return self._msg.message_id
        @property
        def text(self): return self._msg.text or self._msg.caption
        @property
        def chat_id(self): return self._msg.chat_id
        @property
        def author_id(self): return self._msg.from_user.id if self._msg.from_user else self._msg.chat_id
        @property
        def is_group(self): return self._msg.chat.type in ["group", "supergroup", "channel"]
        @property
        def type(self): return self._msg.chat.type

        async def reply(self, text: str, reply_markup: Any = None):
            msg = await self._msg.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(self._update, self._context, msg)

        async def edit(self, text: str, reply_markup: Any = None):
            msg = await self._msg.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(self._update, self._context, msg)

        async def delete(self):
            return await self._msg.delete()

    class TelegramCallbackQuery(CallbackQuery):
        def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            self._update = update
            self._context = context
            self._cq = update.callback_query

        @property
        def id(self): return self._cq.id
        @property
        def data(self): return self._cq.data
        @property
        def message(self): return TelegramMessage(self._update, self._context, self._cq.message)
        @property
        def author_id(self): return self._cq.from_user.id

        async def answer(self, text: str = None, show_alert: bool = False):
            return await self._cq.answer(text=text, show_alert=show_alert)

    class TelegramBotClient(BotClient):
        def __init__(self, bot: Bot):
            self.bot = bot

        async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
            msg = await self.bot.send_message(chat_id, text=text, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id, parse_mode="Markdown")
            return TelegramMessage(None, None, msg)

        async def edit_message(self, chat_id, message_id, text, reply_markup=None):
            msg = await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(None, None, msg)

        async def delete_message(self, chat_id, message_id):
            return await self.bot.delete_message(chat_id, message_id)

        async def send_chat_action(self, chat_id, action):
            action_map = {"typing": "typing", "upload_voice": "upload_voice", "record_voice": "record_voice", "upload_photo": "upload_photo"}
            tg_action = action_map.get(action, action)
            return await self.bot.send_chat_action(chat_id, tg_action)

        async def send_audio(self, chat_id, audio, caption=None, reply_markup=None):
            msg = await self.bot.send_audio(chat_id, audio=audio, caption=caption, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(None, None, msg)

        async def send_voice(self, chat_id, voice, caption=None, reply_markup=None):
            msg = await self.bot.send_voice(chat_id, voice=voice, caption=caption, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(None, None, msg)

        async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
            msg = await self.bot.send_photo(chat_id, photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="Markdown")
            return TelegramMessage(None, None, msg)

        async def forward_message(self, chat_id, from_chat_id, message_id):
            msg = await self.bot.forward_message(chat_id, from_chat_id, message_id)
            return TelegramMessage(None, None, msg)

        async def get_chat(self, chat_id):
            return await self.bot.get_chat(chat_id)

        async def get_chat_member(self, chat_id, user_id):
            return await self.bot.get_chat_member(chat_id, user_id)

        def build_markup(self, buttons):
            if not buttons: return None
            tg_rows = []
            for row in buttons:
                tg_row = []
                for btn in row:
                    btn_copy = btn.copy()
                    if "copy_text" in btn_copy:
                        # Telegram doesn't support Bale-style copy_text button.
                        # As a fallback, we'll convert it to a link if it looks like a URL,
                        # or just drop it. For now, let's keep it as is if it's a URL in 'url'.
                        btn_copy.pop("copy_text")
                        if "url" not in btn_copy:
                            # If only copy_text was provided, we can't really do much in an InlineKeyboardButton
                            # without a callback or url.
                            btn_copy["url"] = "https://t.me/share/url?url=" + btn["copy_text"]

                    if "web_app" in btn_copy and isinstance(btn_copy["web_app"], str):
                        btn_copy["web_app"] = WebAppInfo(url=btn_copy["web_app"])
                    tg_row.append(TGInlineKeyboardButton(**btn_copy))
                tg_rows.append(tg_row)
            return InlineKeyboardMarkup(tg_rows)
except ImportError: pass
