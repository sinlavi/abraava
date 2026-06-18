import aiohttp
from typing import Optional
from aiohttp_socks import ProxyConnector

class HttpClient:
    _session: Optional[aiohttp.ClientSession] = None
    _direct_session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_session(cls, use_proxy: bool = True) -> aiohttp.ClientSession:
        if use_proxy:
            if cls._session is None or cls._session.closed:
                from core.config import PROXY
                if PROXY and PROXY.startswith("socks"):
                    # python-socks does not support socks5h scheme, normalize to socks5
                    proxy_url = PROXY.replace("socks5h://", "socks5://")
                    connector = ProxyConnector.from_url(proxy_url, ssl=False)
                else:
                    connector = aiohttp.TCPConnector(ssl=False)
                cls._session = aiohttp.ClientSession(connector=connector, trust_env=True)
            return cls._session
        else:
            if cls._direct_session is None or cls._direct_session.closed:
                connector = aiohttp.TCPConnector(ssl=False)
                cls._direct_session = aiohttp.ClientSession(connector=connector, trust_env=True)
            return cls._direct_session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
        if cls._direct_session and not cls._direct_session.closed:
            await cls._direct_session.close()
