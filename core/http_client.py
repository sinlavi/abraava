import aiohttp
import asyncio
import logging
from typing import Optional, Any
from aiohttp_socks import ProxyConnector

logger = logging.getLogger("ABRAAVA:HTTP_CLIENT")

class HttpClient:
    _session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            from core.config import PROXY
            connector = None
            if PROXY and PROXY.startswith("socks"):
                # python-socks does not support socks5h scheme, normalize to socks5
                proxy_url = PROXY.replace("socks5h://", "socks5://")
                connector = ProxyConnector.from_url(proxy_url, ssl=False)
            else:
                connector = aiohttp.TCPConnector(ssl=False)

            timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
            cls._session = aiohttp.ClientSession(
                connector=connector,
                trust_env=True,
                timeout=timeout
            )
        return cls._session

    @classmethod
    async def request(cls, method: str, url: str, retries: int = 3, **kwargs: Any) -> Optional[aiohttp.ClientResponse]:
        session = await cls.get_session()
        for attempt in range(retries):
            try:
                resp = await session.request(method, url, **kwargs)
                if resp.status >= 500 and attempt < retries - 1:
                    logger.warning(f"Server error {resp.status} for {url}, retrying {attempt+1}...")
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                return resp
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < retries - 1:
                    logger.warning(f"Request failed for {url}: {e}, retrying {attempt+1}...")
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    logger.error(f"Request failed for {url} after {retries} attempts: {e}")
                    raise
        return None

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
