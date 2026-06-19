from services.lyrics_service import lyrics_service
import asyncio, os, shutil
from pathlib import Path
from typing import Optional, Union, List
from core.logger import logger
from core.config import OFFLINE_MODE, DEFAULT_QUALITY, FOOTER, PLATFORM
from core.http_client import HttpClient
from crawlers.utils import get_track
from crawlers.youtube import search_youtube_track, download_audio
from crawlers.itunes import get_cached_audio, set_mirror
from utils.helpers import format_duration, generate_deep_link
from utils.messages import send_message, edit_message, safe_delete
from bot.keyboards import create_close_button

class DownloadService:
    def __init__(self, bot, api_client, user_settings_service, artwork_service, tagging_service, error_notifier, album_tracker, download_rate_limiter):
        self.bot, self.api_client, self.user_settings_service, self.artwork_service, self.tagging_service, self.error_notifier, self.album_tracker, self.download_rate_limiter = bot, api_client, user_settings_service, artwork_service, tagging_service, error_notifier, album_tracker, download_rate_limiter
        self.download_semaphore = asyncio.Semaphore(20)
    async def _update_status(self, chat_id, status_msg, text, status_prefix="", reply_markup=None, is_batch=False):
        txt = f"{status_prefix}\n\n{text}" if status_prefix else text
        return await edit_message(status_msg, txt, reply_markup=reply_markup, show_cancel=not is_batch) if status_msg else await send_message(self.bot, chat_id, txt, reply_markup=reply_markup, show_cancel=not is_batch)
    async def download_and_send_track(self, chat_id, track_id, user_id, status_msg=None, is_batch=False, album_cover_bytes=None, collection_id=None, selected_quality=None, track_name_hint=None, track_index=None, status_prefix="", reply_markup=None, skip_size_check=False):
        status_msg = await self._update_status(chat_id, status_msg, f"🔍 *({track_index}) *در حال دریافت اطلاعات آهنگ {track_name_hint if track_name_hint else ''}...*", status_prefix, reply_markup, is_batch) if status_msg is None else await self._update_status(chat_id, status_msg, "🔍 *در حال دریافت اطلاعات آهنگ...*", status_prefix, reply_markup, is_batch)
        data = await get_track(track_id)
        if not data or not data.get("results"): return await self._update_status(chat_id, status_msg, "خطا در دریافت اطلاعات آهنگ.", status_prefix, reply_markup, is_batch), False
        track = data["results"][0]
        if not is_batch:
            status_prefix = f"🎵 *آهنگ:* {track.get('trackName')}\n🎤 *هنرمند:* {track.get('artistName')}"
            if track.get('collectionName'): status_prefix += f"\n💿 *آلبوم:* {track.get('collectionName')}"
        quality_value = selected_quality or (await self.user_settings_service.get_settings(user_id)).download_quality.value
        if quality_value == "ask": quality_value = DEFAULT_QUALITY
        duration_ms = int(track.get('trackTimeMillis') or 0)
        if PLATFORM == "bale" and not skip_size_check and duration_ms > 0:
            def est(d, b): return round((int(b) * (d / 1000)) / (8 * 1024), 2)
            for q in [quality_value, "192", "128"]:
                if est(duration_ms, q) < 19.5: safe_q = q; break
            else: safe_q = None
            if safe_q != quality_value:
                if not is_batch: return await self._update_status(chat_id, status_msg, f"⚠️ *حجم فایل با کیفیت {quality_value} بیشتر از ۲۰ مگابایت است.*\n\nآیا مایلید با کیفیت {safe_q} دانلود شود؟", status_prefix, [[{"text": f"📥 دانلود با کیفیت {safe_q}", "callback_data": f"dl_fb:{safe_q}:{track_id}:u{user_id}"}], [{"text": "❌ انصراف", "callback_data": f"close:u{user_id}"}]], is_batch), False
                quality_value = safe_q
        caption, cache = self._build_caption(track, quality_value), await get_cached_audio(track_id, quality=quality_value)
        if cache:
            try:
                await self._update_status(chat_id, status_msg, "📤 *در حال ارسال فایل از حافظه کش...*", status_prefix, reply_markup, is_batch)
                await self.bot.send_chat_action(chat_id, "upload_voice"); await self.bot.send_audio(chat_id, audio=cache, caption=caption, reply_markup=self._build_audio_markup(track_id, track.get("trackViewUrl"), user_id=user_id))
                if not is_batch: await safe_delete(status_msg)
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''), track.get('artistName', ''), track.get('collectionName', ''), 0, 'cache', quality_value); return status_msg, True
            except: pass
        if OFFLINE_MODE: return await self._update_status(chat_id, status_msg, "بات در حالت آفلاین است.", status_prefix, reply_markup, is_batch), False
        cover = album_cover_bytes or (await self.artwork_service.get_artwork_bytes(track.get('collectionId') or track_id, track.get('artworkUrl100')) if (await self.user_settings_service.get_settings(user_id)).show_artwork else None)
        url = track.get("trackViewUrl") if isinstance(track_id, str) and track_id.startswith(("yt_", "sc_")) else None
        if not url:
            await self._update_status(chat_id, status_msg, "🔍 *در حال جستجوی منبع با کیفیت...*", status_prefix, reply_markup, is_batch)
            vid = await search_youtube_track(track.get("trackName", ""), track.get("artistName", ""), track.get("collectionName", ""), (track.get("releaseDate") or "")[:4], target_duration_ms=duration_ms)
            if not vid: return await self._update_status(chat_id, status_msg, "❌ منبعی برای ترک خواسته شده پیدا نشد.", status_prefix, reply_markup, is_batch), False
            url = f"https://music.youtube.com/watch?v={vid}"
        temp_dir = None
        try:
            async with self.download_semaphore:
                if collection_id: self.album_tracker.start_track(user_id, collection_id, track.get("trackName", ""))
                await self._update_status(chat_id, status_msg, f"⏳ *در حال دانلود با کیفیت {quality_value}kbps...*", status_prefix, reply_markup, is_batch); await self.bot.send_chat_action(chat_id, "record_voice")
                path = await download_audio(url, quality=quality_value)
                if not path: raise Exception("DL failed")
                temp_dir = os.path.dirname(path); await self._update_status(chat_id, status_msg, "🏷️ *در حال تگ‌گذاری فایل...*", status_prefix, reply_markup, is_batch)
                lyr = await lyrics_service.get_lyrics(track_id, track.get("trackName", ""), track.get("artistName", ""), track.get("collectionName"))
                self.tagging_service.tag_mp3(Path(path), track, cover, lyrics=(lyr.get("synced") or lyr.get("plain")) if lyr else None)
                await self._update_status(chat_id, status_msg, "☁️ *در حال آپلود روی سرورهای ابری...*", status_prefix, reply_markup, is_batch); await self.bot.send_chat_action(chat_id, "upload_voice")
                with open(path, 'rb') as f:
                    msg = await self.bot.send_audio(chat_id, audio=f, caption=caption, reply_markup=self._build_audio_markup(track_id, track.get("trackViewUrl"), user_id=user_id))
                    if msg and track_id:
                        fid = msg._msg.audio.id if PLATFORM == "bale" else msg._msg.audio.file_id
                        await set_mirror('track', str(track_id), 'audioUrl', f"tg://file/{fid}" if PLATFORM == "telegram" else f"https://tapi.bale.ai/file/bot<token>/{fid}", quality=quality_value)
                await self.api_client.log_download(user_id, str(track_id), track.get('trackName', ''), track.get('artistName', ''), track.get('collectionName', ''), os.path.getsize(path), 'youtube', quality_value); self.download_rate_limiter.record_download(user_id, quality_value)
                if not is_batch: await safe_delete(status_msg)
                return status_msg, True
        except Exception as e:
            logger.error(f"DL error: {e}"); return await self._update_status(chat_id, status_msg, f"❌ خطا در دانلود {track.get('trackName', '')}", status_prefix, [[{"text": "🔄 تلاش مجدد", "callback_data": f"retry:download_retry:{track_id}:u{user_id}"}]], is_batch), False
        finally:
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)
    def _build_caption(self, track, quality):
        tid, is_sc = track.get('trackId', ''), str(track.get('trackId', '')).startswith("sc_")
        art_id, art_name = track.get('artistId'), track.get('artistName')
        art_link = art_name if is_sc else (f"[{art_name}]({generate_deep_link('artist', art_id)})" if art_id else art_name)
        col_id, col_name = track.get('collectionId'), track.get('collectionName')
        col_link = (f"[{col_name}]({generate_deep_link('collection', col_id)})" if col_id else col_name) if col_name and not is_sc else None
        tn_link = f"[{track.get('trackName')}]({generate_deep_link('track', tid)})" if track.get('trackName') else None
        fields = {"🎵 نام آهنگ": tn_link, "🎤 نام هنرمند": art_link, "💿 نام آلبوم": col_link, "📅 سال انتشار": str(track.get('releaseDate', ''))[:4] if track.get('releaseDate') else None, "🎸 سبک": track.get('primaryGenreName'), "⏱️ مدت زمان": format_duration(track.get('trackTimeMillis', 0)) if track.get('trackTimeMillis') else None, "📀 کیفیت دانلود": f"{quality} kbps"}
        return "\n".join([f"{k}: {v}" for k, v in fields.items() if v and str(v).strip() and "Unknown" not in str(v)]) + f"\n\n{FOOTER}"
    def _build_audio_markup(self, tid, url=None, user_id=None):
        m = []
        if not str(tid).startswith(("yt_", "sc_", "sp_")): m.append([{"text": "📂 نمایش در مینی اپ", "web_app": f"https://3rah.ir/music/ui?id={tid}"}])
        m.extend([[{"text": "📋 کپی پیوند", "copy_text": generate_deep_link("track", tid)}], [{"text": "🌐 اطلاعات بیشتر", "url": url or f"https://player.abraava.ir?id={tid}"}], [create_close_button(user_id)]])
        return m

cat <<EOF > services/direct_download_service.py
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
