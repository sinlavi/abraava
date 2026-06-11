import asyncio
import logging

from utils.messages import send_message, edit_message, safe_delete
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks
from bot.keyboards import create_close_button

logger = logging.getLogger("ABRAAVA:ALBUM_DL")

async def download_album(bot, chat_id, collection_id, user_id, download_service, quality=None, status_msg=None, retry_ids=None):
    if status_msg:
        await safe_delete(status_msg)

    parent_msg = await send_message(bot, chat_id, "⏳ *شروع فرایند دانلود...*")

    # Use a dummy collection ID for manual retries if not provided
    lock_id = collection_id or f"retry_{user_id}_{int(asyncio.get_event_loop().time())}"

    if not await download_service.album_tracker.acquire_lock(user_id, lock_id):
        await safe_delete(parent_msg)
        parent_msg = await send_message(bot, chat_id, "❌ *در حال حاضر یک فرایند دانلود برای شما در حال انجام است*")
        return

    success_count = 0
    failed_count = 0
    failed_tracks = []
    coll_name = "قطعات انتخابی"

    try:
        if retry_ids:
            tracks = []
            for tid in retry_ids:
                from crawlers.utils import get_track
                t_data = await get_track(tid)
                if t_data and t_data.get("results"):
                    tracks.append(t_data["results"][0])
        else:
            collection_data = await get_or_crawl_collection(collection_id)
            tracks_data = await get_or_crawl_collection_tracks(collection_id)

            if not collection_data or not tracks_data:
                await safe_delete(parent_msg)
                parent_msg = await send_message(bot, chat_id, "❌ اطلاعات یافت نشد")
                return

            coll = collection_data['results'][0]
            tracks = tracks_data['results']
            coll_name = coll.get('collectionName', 'آلبوم')

        album_markup = [[{"text": "⏹️ توقف دانلود", "callback_data": f"cancel_album:{lock_id}:u{user_id}"}]]
        await safe_delete(parent_msg)
        parent_msg = await send_message(bot, chat_id, f"📀 *نام:* {coll_name}\n🎵 *تعداد قطعات:* {len(tracks)}\n⬇️ *در حال دانلود...*", reply_markup=album_markup)

        download_service.album_tracker.start_download(user_id, lock_id, parent_msg, len(tracks), coll_name)

        album_cover_bytes = None
        if not retry_ids:
            album_cover_bytes = await download_service.artwork_service.get_artwork_bytes(coll.get('collectionId'), coll.get('artworkUrl100'))

        settings = await download_service.user_settings_service.get_settings(user_id)
        quality_value = quality or settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        for idx, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, lock_id):
                break

            track_name = track.get('trackName', 'Unknown')
            progress_prefix = (
                f"📀 *نام:* {coll_name}\n"
                f"📊 *وضعیت:* {idx}/{len(tracks)} قطعه\n"
                f"✅ *موفق:* {success_count}   \n❌ *ناموفق:* {failed_count}\n"
                f"⏳ *در حال پردازش:* {track_name}"
            )

            try:
                # Delete previous and send new to stay at bottom
                if parent_msg: await safe_delete(parent_msg)
                parent_msg = None

                parent_msg, success = await download_service.download_and_send_track(
                    chat_id, track['trackId'], user_id,
                    status_msg=None,
                    is_batch=True, album_cover_bytes=album_cover_bytes,
                    collection_id=lock_id, selected_quality=quality_value,
                    track_name_hint=track_name, track_index=idx,
                    status_prefix=progress_prefix,
                    reply_markup=album_markup
                )

                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_tracks.append((track.get('trackId'), track_name))

            except Exception as e:
                logger.error(f"Error downloading track {idx}: {e}")
                failed_count += 1
                failed_tracks.append((track.get('trackId'), track_name))

            await asyncio.sleep(0.3)

        # Final Summary
        is_cancelled = download_service.album_tracker.is_cancelled(user_id, lock_id)
        await _send_album_summary(bot, chat_id, coll_name, len(tracks), success_count, failed_count, failed_tracks, user_id, parent_msg, is_cancelled)
        parent_msg = None # Summary handles it

    finally:
        download_service.album_tracker.finish_download(user_id, lock_id, success_count, failed_count)

async def _send_album_summary(bot, chat_id, coll_name, total, success, failed, failed_tracks, user_id, status_msg, is_cancelled):
    if is_cancelled:
        final_text = f"⏹️ *فرایند دانلود {coll_name} متوقف شد.*\n\n"
    else:
        final_text = f"🏁 *فرایند دانلود به پایان رسید!*\n\n"

    final_text += (
        f"💿 *نام:* {coll_name}\n"
        f"🎵 *مجموع قطعات:* {total}\n"
        f"✅ *موفق:* {success}\n"
    )

    markup_rows = []
    if failed > 0:
        final_text += f"❌ *ناموفق:* {failed}\n\n"
        final_text += "📑 *لیست قطعات دانلود نشده:*\n"
        for _, name in failed_tracks[:15]:
            final_text += f"🔸 {name}\n"
        if len(failed_tracks) > 15:
            final_text += f"و {len(failed_tracks) - 15} مورد دیگر...\n"

        failed_ids = ",".join([str(tid) for tid, _ in failed_tracks])
        if len(failed_ids) < 100: # Increased limit for Bale
            markup_rows.append([{"text": "🔄 تلاش مجدد قطعات ناموفق", "callback_data": f"retry_failed:{failed_ids}:u{user_id}"}])

    markup_rows.append([create_close_button(user_id)])

    if status_msg: await safe_delete(status_msg)
    await send_message(bot, chat_id, final_text, reply_markup=markup_rows)
