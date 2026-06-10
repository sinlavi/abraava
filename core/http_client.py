import aiohttp
from typing import Optional

class HttpClient:
    _session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            # trust_env=True allows aiohttp to use proxy from environment variables (HTTP_PROXY, etc.)
            cls._session = aiohttp.ClientSession(connector=connector, trust_env=True)
        return cls._session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
