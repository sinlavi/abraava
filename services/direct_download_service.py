import asyncio, os, shutil, random, uuid, logging
from pathlib import Path
import yt_dlp
from core.config import PROXY, FOOTER
from core.logger import logger
from bot.keyboards import create_close_button
from services.lyrics_service import lyrics_service

class DirectDownloadService:
    def __init__(self, bot, tagging_service): self.bot, self.tagging_service = bot, tagging_service
    def _build_opts(self, url, out=None, q="192", m=1):
        o = {'format': 'bestaudio/best', 'quiet': True, 'no_check_certificate': True, 'http_headers': {'User-Agent': random.choice(["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"])}, 'retries': 5}
        if out: o['outtmpl'], o['postprocessors'] = f'{out}/%(title)s.%(ext)s', [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': q}]
        else: o['skip_download'] = True
        if m == 2 and PROXY: o['proxy'] = PROXY
        elif m == 3:
            if "youtube.com" in url or "youtu.be" in url: o['extractor_args'] = {"youtube": {"player_client": ["web", "mweb", "android_vr"]}}
            if PROXY: o['proxy'] = PROXY
        return o
    async def get_metadata(self, url):
        for m in [1, 2, 3]:
            try:
                with yt_dlp.YoutubeDL(self._build_opts(url, m=m)) as ydl:
                    i = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    return {'title': i.get('title', 'Unknown'), 'uploader': i.get('uploader', i.get('artist', 'Unknown')), 'album': i.get('album', ''), 'url': url, 'upload_date': i.get('upload_date', ''), 'thumbnail': i.get('thumbnail'), 'duration': i.get('duration')}
            except: continue
        return None
    async def ask_confirmation(self, chat_id, url, user_id=None, reply_to=None):
        from utils.messages import send_message, edit_message, safe_delete
        from utils.helpers import format_duration
        from bot.handlers.callbacks import DIRECT_LINKS
        s = await send_message(self.bot, chat_id, "⏳ *در حال دریافت اطلاعات از پیوند...*", reply_to_message_id=reply_to)
        meta = await self.get_metadata(url)
        if not meta: await edit_message(s, "❌ خطا در دریافت اطلاعات پیوند."); return
        txt = "🎵 *اطلاعات یافت شده:*\n\n" + "\n".join([f"{k}: {v}" for k, v in {"🎵 نام آهنگ": f"[{meta['title']}]({url})", "🎤 نام هنرمند": meta['uploader'], "💿 نام آلبوم": meta['album'], "📅 سال انتشار": meta['upload_date'][:4], "⏱️ مدت زمان": format_duration(int(meta.get('duration', 0)) * 1000)}.items() if v]) + "\n\nآیا مایل به دانلود این ترک هستید؟"
        lid = uuid.uuid4().hex[:8]; DIRECT_LINKS[lid] = url
        m = [[{"text": "✅ بله، دانلود کن", "callback_data": f"confirm_dl:{lid}:u{user_id}"}], [create_close_button(user_id)]]
        if meta.get("thumbnail"):
            try: await self.bot.send_chat_action(chat_id, "upload_photo"); await self.bot.send_photo(chat_id, photo=meta["thumbnail"], caption=f"{txt}{FOOTER}", reply_markup=m); await safe_delete(s)
            except: await edit_message(s, txt, reply_markup=m)
        else: await edit_message(s, txt, reply_markup=m)
    async def download_direct(self, chat_id, url, user_id, quality="192"):
        from utils.messages import send_message, safe_delete
        s = await send_message(self.bot, chat_id, f"⏳ *در حال شروع دانلود...*")
        uid = uuid.uuid4().hex; d = os.path.join(os.getcwd(), "downloads", uid); os.makedirs(d, exist_ok=True); succ, tdata, path = False, {}, None
        try:
            for m in [1, 2, 3]:
                try:
                    await self.bot.send_chat_action(chat_id, "record_voice")
                    with yt_dlp.YoutubeDL(self._build_opts(url, out=d, q=quality, m=m)) as ydl:
                        i = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                        tdata = {'trackName': i.get('title', 'Unknown'), 'artistName': i.get('uploader', i.get('artist', 'Unknown')), 'collectionName': i.get('album', ''), 'releaseDate': i.get('upload_date', '')[:4]}
                        files = list(Path(d).glob("*.mp3"))
                        if files: path = files[0]; succ = True; break
                except: continue
            if succ and path:
                await safe_delete(s); s = await send_message(self.bot, chat_id, "☁️ *در حال آماده‌سازی فایل...*")
                lyr = await lyrics_service.get_lyrics(f"direct_{uid}", tdata['trackName'], tdata['artistName'], tdata['collectionName'])
                self.tagging_service.tag_mp3(path, tdata, lyrics=(lyr.get("synced") or lyr.get("plain")) if lyr else None)
                cap = "\n".join([f"{k}: {v}" for k, v in {"🎵 نام آهنگ": f"[{tdata['trackName']}]({url})", "🎤 نام هنرمند": tdata['artistName'], "💿 نام آلبوم": tdata['collectionName'], "📀 کیفیت دانلود": f"{quality} kbps"}.items() if v])
                with open(path, 'rb') as f:
                    await self.bot.send_chat_action(chat_id, "upload_voice"); await self.bot.send_audio(chat_id, audio=f, caption=f"{cap}{FOOTER}", reply_markup=[[{"text": "📋 کپی پیوند", "copy_text": url}], [{"text": "🌐 اطلاعات بیشتر", "url": url}], [create_close_button(user_id)]])
                await safe_delete(s); return s, True
            else: await safe_delete(s); await send_message(self.bot, chat_id, "❌ دانلود با خطا مواجه شد."); return None, False
        except Exception as e: logger.error(f"Direct DL error: {e}"); await safe_delete(s); await send_message(self.bot, chat_id, f"❌ خطا: {str(e)[:50]}"); return None, False
        finally: shutil.rmtree(d, ignore_errors=True)
