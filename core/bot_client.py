from abc import ABC, abstractmethod
from typing import Any, Optional, Union, List
from core.config import PLATFORM, FOOTER, TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_TOKEN
from core.logger import logger
import asyncio

class BotClient(ABC):
    def __init__(self, token: str):
        self.token = token

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def send_message(self, chat_id: Union[int, str], text: str, reply_markup: Any = None, reply_to_message_id: Any = None, no_footer: bool = False) -> Any:
        pass

    @abstractmethod
    async def edit_message(self, chat_id: Union[int, str], message_id: Any, text: str, reply_markup: Any = None, no_footer: bool = False) -> Any:
        pass

    @abstractmethod
    async def delete_message(self, chat_id: Union[int, str], message_id: Any) -> bool:
        pass

    @abstractmethod
    async def send_chat_action(self, chat_id: Union[int, str], action: str):
        pass

    @abstractmethod
    async def send_audio(self, chat_id: Union[int, str], audio: Any, caption: str = "", reply_markup: Any = None, no_footer: bool = False) -> Any:
        pass

    @abstractmethod
    async def send_photo(self, chat_id: Union[int, str], photo: Any, caption: str = "", reply_markup: Any = None, no_footer: bool = False) -> Any:
        pass

    @abstractmethod
    async def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        pass

class BalethonClient(BotClient):
    def __init__(self, token: str):
        super().__init__(token)
        from balethon import Client
        self.client = Client(token)

    async def start(self):
        # Balethon client.run() handles connection, but we can use connect() if we use it in a custom loop
        pass

    def _convert_markup(self, markup):
        if markup is None: return None
        from balethon.objects import InlineKeyboard, InlineKeyboardButton
        if isinstance(markup, list):
            rows = []
            for row in markup:
                if isinstance(row, list):
                    rows.append([InlineKeyboardButton(**btn) if isinstance(btn, dict) else btn for btn in row])
                else:
                    rows.append([InlineKeyboardButton(**row) if isinstance(row, dict) else row])
            return InlineKeyboard(*rows)
        return markup

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, no_footer=False):
        full_text = text if no_footer else f"{text}{FOOTER}"
        return await self.client.send_message(chat_id, text=full_text, reply_markup=self._convert_markup(reply_markup), reply_to_message_id=reply_to_message_id)

    async def edit_message(self, chat_id, message_id, text, reply_markup=None, no_footer=False):
        full_text = text if no_footer else f"{text}{FOOTER}"
        return await self.client.edit_message(chat_id, message_id, text=full_text, reply_markup=self._convert_markup(reply_markup))

    async def delete_message(self, chat_id, message_id):
        return await self.client.delete_message(chat_id, message_id)

    async def send_chat_action(self, chat_id, action):
        return await self.client.send_chat_action(chat_id, action)

    async def send_audio(self, chat_id, audio, caption="", reply_markup=None, no_footer=False):
        full_caption = caption if no_footer else f"{caption}{FOOTER}"
        return await self.client.send_audio(chat_id, audio=audio, caption=full_caption, reply_markup=self._convert_markup(reply_markup))

    async def send_photo(self, chat_id, photo, caption="", reply_markup=None, no_footer=False):
        full_caption = caption if no_footer else f"{caption}{FOOTER}"
        return await self.client.send_photo(chat_id, photo=photo, caption=full_caption, reply_markup=self._convert_markup(reply_markup))

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        return await self.client.answer_callback_query(callback_query_id, text=text, show_alert=show_alert)

class TelethonClient(BotClient):
    def __init__(self, token: str, api_id: int, api_hash: str):
        super().__init__(token)
        from telethon import TelegramClient
        self.client = TelegramClient('bot_session', api_id, api_hash)
        self._bot_token = token

    async def start(self):
        await self.client.start(bot_token=self._bot_token)

    def _convert_markup(self, markup):
        if markup is None: return None
        from telethon import Button
        if isinstance(markup, list):
            rows = []
            for row in markup:
                new_row = []
                for btn in row:
                    if hasattr(btn, "text"):
                        if hasattr(btn, "url") and btn.url:
                            new_row.append(Button.url(btn.text, btn.url))
                        elif hasattr(btn, "callback_data") and btn.callback_data:
                            new_row.append(Button.inline(btn.text, btn.callback_data))
                        elif hasattr(btn, "switch_inline_query"):
                            new_row.append(Button.switch_inline(btn.text, btn.switch_inline_query))
                        else:
                            new_row.append(Button.text(btn.text))
                    else:
                        new_row.append(btn)
                rows.append(new_row)
            return rows
        return markup

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, no_footer=False):
        full_text = text if no_footer else f"{text}{FOOTER}"
        return await self.client.send_message(chat_id, full_text, buttons=self._convert_markup(reply_markup), reply_to=reply_to_message_id)

    async def edit_message(self, chat_id, message_id, text, reply_markup=None, no_footer=False):
        full_text = text if no_footer else f"{text}{FOOTER}"
        return await self.client.edit_message(chat_id, message_id, full_text, buttons=self._convert_markup(reply_markup))

    async def delete_message(self, chat_id, message_id):
        return await self.client.delete_messages(chat_id, message_id)

    async def send_chat_action(self, chat_id, action):
        # Telethon action mapping
        action_map = {
            "typing": "typing",
            "upload_photo": "photo",
            "record_voice": "record-audio",
            "upload_voice": "audio"
        }
        async with self.client.action(chat_id, action_map.get(action, "typing")):
            await asyncio.sleep(0) # Just to trigger the context manager

    async def send_audio(self, chat_id, audio, caption="", reply_markup=None, no_footer=False):
        full_caption = caption if no_footer else f"{caption}{FOOTER}"
        return await self.client.send_file(chat_id, audio, caption=full_caption, buttons=self._convert_markup(reply_markup), voice=False)

    async def send_photo(self, chat_id, photo, caption="", reply_markup=None, no_footer=False):
        full_caption = caption if no_footer else f"{caption}{FOOTER}"
        return await self.client.send_file(chat_id, photo, caption=full_caption, buttons=self._convert_markup(reply_markup))

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        # In Telethon, we actually need the event object to answer, or we can use the library's answer method if we have the query ID
        # However, Telethon query answers are usually done on the event itself.
        # This is a bit tricky with just an ID.
        # But we can try to use Client.answer_callback_query(query_id, text, alert=show_alert)
        from telethon import functions
        return await self.client(functions.messages.SetBotCallbackAnswerRequest(
            query_id=int(callback_query_id),
            message=text,
            alert=show_alert
        ))

_instance = None

def get_bot_client() -> BotClient:
    global _instance
    if _instance is None:
        if PLATFORM == "telegram":
            _instance = TelethonClient(BOT_TOKEN, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        else:
            _instance = BalethonClient(BOT_TOKEN)
    return _instance
