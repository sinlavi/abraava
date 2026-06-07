import asyncio
import os
import re
import socket
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

import yt_dlp
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from core.config import PROXY
from core.logger import logger
from utils.messages import send_message, edit_message, safe_delete
from bot.keyboards import create_close_button

def _get_cookies_path() -> Optional[str]:
    """Get path to cookies.txt in root folder."""
    script_dir = Path(__file__).parent.parent
    cookies_path = script_dir / "cookies.txt"
    if cookies_path.exists() and cookies_path.is_file():
        return str(cookies_path)
    return None

class DirectDownloadService:
    def __init__(self, bot, tagging_service):
        self.bot = bot
        self.tagging_service = tagging_service

    def _get_proxy(self):
        """Return SOCKS5 proxy URL from config or check for local WARP/Dante."""
        if PROXY: return PROXY
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", 1080)) == 0:
                return "socks5://127.0.0.1:1080"
        except: pass
        finally: s.close()
        return None

    def _get_ydl_opts(self, method, output_dir, proxy=None):
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{output_dir}/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'quiet': True,
            'no_check_certificate': True,
        }
        cookies = _get_cookies_path()
        if cookies: opts['cookiefile'] = cookies

        if method == 2 and proxy:
            opts['proxy'] = proxy
        elif method == 3:
            opts['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
            if proxy: opts['proxy'] = proxy
        return opts

    async def ask_confirmation(self, chat_id, url, user_id=None):
        """Show metadata preview and ask for download confirmation."""
        status_msg = await send_message(self.bot, chat_id, "🔍 *در حال دریافت اطلاعات پیوند...*")

        proxy = self._get_proxy()
        loop = asyncio.get_event_loop()

        info = None
        for method in [1, 2, 3]:
            try:
                opts = {'quiet': True, 'no_check_certificate': True, 'extract_flat': True}
                cookies = _get_cookies_path()
                if cookies: opts['cookiefile'] = cookies
                if method == 2 and proxy: opts['proxy'] = proxy

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info: break
            except Exception as e:
                logger.debug(f"Direct link metadata method {method} failed: {e}")

        if not info:
            await edit_message(status_msg, "❌ متأسفانه اطلاعاتی برای این پیوند یافت نشد.")
            return

        title = info.get("title", "Unknown")
        uploader = info.get("uploader", "Unknown")
        duration = info.get("duration", 0)

        text = (
            f"🎵 *اطلاعات پیوند شناسایی شده:*\n\n"
            f"🔸 نام: {title}\n"
            f"🔸 هنرمند/آپلودر: {uploader}\n"
            f"⏱️ مدت زمان: {int(duration // 60)}:{int(duration % 60):02d}\n\n"
            "آیا مایل به دانلود این فایل هستید؟"
        )

        markup = [
            [InlineKeyboardButton(text="📥 بله، دانلود شود", callback_data=f"confirm_dl:{url}")],
            [create_close_button(user_id)]
        ]

        await edit_message(status_msg, text, reply_markup=InlineKeyboard(*markup))
