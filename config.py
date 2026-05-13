import logging
import os
from typing import Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "ابرآوا"
BOT_USERNAME = "@abraava_bot"
INFO_CHANNEL_USERNAME = "@abraava"
FOOTER = '\n\n' + BOT_USERNAME + '\n' + INFO_CHANNEL_USERNAME

ITUNES_BASE_URL = "https://itunes.apple.com"
BOT_TOKEN = os.environ.get("BOT_TOKEN", None)
DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID", None)
INFO_CHANNEL_ID = '5524168471'
BROADCAST_CHANNELS = [INFO_CHANNEL_ID, '4783738693']
ITEMS_PER_PAGE = 7
OFFLINE_MODE = False
logger = logging.getLogger("ABRAAVA")


class HttpClient:
    session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_session(cls):
        if cls.session is None or cls.session.closed:
            connector = aiohttp.TCPConnector()
            cls.session = aiohttp.ClientSession(connector=connector)
        return cls.session

    @classmethod
    async def close(cls):
        if cls.session and not cls.session.closed:
            await cls.session.close()
