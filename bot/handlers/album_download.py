import asyncio, logging
from utils.messages import send_message, safe_delete
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks
from bot.keyboards import create_close_button

logger = logging.getLogger("ABRAAVA:ALBUM_DL")

async def download_album(bot, chat_id, collection_id, user_id, download_service, quality=None, status_msg=None, retry_ids=None):
    if status_msg: await safe_delete(status_msg)
    parent_msg = await send_message(bot, chat_id, "⏳ *شروع فرایند دانلود...*")
    lock_id = collection_id or f"retry_{user_id}_{int(asyncio.get_event_loop().time())}"
    if not await download_service.album_tracker.acquire_lock(user_id, lock_id):
        await safe_delete(parent_msg); await send_message(bot, chat_id, "❌ *در حال حاضر یک فرایند دانلود برای شما در حال انجام است*"); return
    success_count, failed_count, failed_tracks, coll_name = 0, 0, [], "قطعات انتخابی"
    try:
        if retry_ids:
            tracks = []
            for tid in retry_ids:
                from crawlers.utils import get_track
                t_data = await get_track(tid)
                if t_data and t_data.get("results"): tracks.append(t_data["results"][0])
        else:
            collection_data, tracks_data = await get_or_crawl_collection(collection_id), await get_or_crawl_collection_tracks(collection_id)
            if not collection_data or not tracks_data: await safe_delete(parent_msg); await send_message(bot, chat_id, "❌ اطلاعات یافت نشد"); return
            coll, tracks, coll_name = collection_data['results'][0], tracks_data['results'], collection_data['results'][0].get('collectionName', 'آلبوم')
        album_markup = [[{"text": "⏹️ توقف دانلود", "callback_data": f"cancel_album:{lock_id}:u{user_id}"}]]
        await safe_delete(parent_msg); parent_msg = await send_message(bot, chat_id, f"📀 *نام:* {coll_name}\n🎵 *تعداد قطعات:* {len(tracks)}\n⬇️ *در حال دانلود...*", reply_markup=album_markup)
        download_service.album_tracker.start_download(user_id, lock_id, parent_msg, len(tracks), coll_name)
        album_cover_bytes = await download_service.artwork_service.get_artwork_bytes(coll.get('collectionId'), coll.get('artworkUrl100')) if not retry_ids else None
        settings = await download_service.user_settings_service.get_settings(user_id)
        quality_value = quality or (settings.download_quality.value if settings.download_quality.value != "ask" else "192")
        for idx, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, lock_id): break
            track_name, progress_prefix = track.get('trackName', 'Unknown'), f"📀 *نام:* {coll_name}\n📊 *وضعیت:* {idx}/{len(tracks)} قطعه\n✅ *موفق:* {success_count}   \n❌ *ناموفق:* {failed_count}\n⏳ *در حال پردازش:* {track.get('trackName', 'Unknown')}"
            try:
                if parent_msg: await safe_delete(parent_msg)
                parent_msg, success = await download_service.download_and_send_track(chat_id, track['trackId'], user_id, status_msg=None, is_batch=True, album_cover_bytes=album_cover_bytes, collection_id=lock_id, selected_quality=quality_value, track_name_hint=track_name, track_index=idx, status_prefix=progress_prefix, reply_markup=album_markup)
                if success: success_count += 1
                else: failed_count += 1; failed_tracks.append((track.get('trackId'), track_name))
            except Exception as e: logger.error(f"Error downloading track {idx}: {e}"); failed_count += 1; failed_tracks.append((track.get('trackId'), track_name))
            await asyncio.sleep(0.3)
        is_cancelled = download_service.album_tracker.is_cancelled(user_id, lock_id)
        final_text = f"{'⏹️ *فرایند دانلود متوقف شد.*' if is_cancelled else '🏁 *فرایند دانلود به پایان رسید!*'}\n\n💿 *نام:* {coll_name}\n🎵 *مجموع قطعات:* {len(tracks)}\n✅ *موفق:* {success_count}"
        markup_rows = []
        if failed_count > 0:
            final_text += f"\n❌ *ناموفق:* {failed_count}\n\n📑 *لیست قطعات دانلود نشده:*\n" + "\n".join([f"🔸 {name}" for _, name in failed_tracks[:15]]) + (f"\nو {len(failed_tracks) - 15} مورد دیگر..." if len(failed_tracks) > 15 else "")
            failed_ids = ",".join([str(tid) for tid, _ in failed_tracks])
            if len(failed_ids) < 100: markup_rows.append([{"text": "🔄 تلاش مجدد قطعات ناموفق", "callback_data": f"retry_failed:{failed_ids}:u{user_id}"}])
        markup_rows.append([create_close_button(user_id)])
        if parent_msg: await safe_delete(parent_msg)
        await send_message(bot, chat_id, final_text, reply_markup=markup_rows)
    finally: download_service.album_tracker.finish_download(user_id, lock_id, success_count, failed_count)
