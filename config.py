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
# PROXY_URL = "http://127.0.0.1:8085"        # change if needed
# VERIFY_SSL = False

ITUNES_BASE_URL = "https://itunes.apple.com"
BOT_TOKEN = os.environ.get("BOT_TOKEN", None)
DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID", None)
INFO_CHANNEL_ID = os.environ.get("INFO_CHANNEL_ID", None)
ITEMS_PER_PAGE = 10
OFFLINE_MODE = os.environ.get("OFFLINE_MODE", "false").lower() in ("true", "1", "yes")
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
