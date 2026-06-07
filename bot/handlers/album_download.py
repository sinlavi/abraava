from core.platform import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message, safe_delete
from bot.keyboards import create_close_button, create_retry_button
import asyncio
import logging

logger = logging.getLogger("ABRAAVA:ALBUM_DOWNLOAD")

async def download_album(bot, chat_id, collection_id, user_id, download_service, quality=None, status_msg=None):
    # 1. Check for active download lock
    if not await download_service.album_tracker.acquire_lock(user_id, collection_id):
        await send_message(bot, chat_id, "⚠️ *یک دانلود فعال برای این آلبوم در حال اجراست.*\n\nلطفا تا اتمام دانلود قبلی منتظر بمانید.")
        return

    try:
        if status_msg:
            status_msg = await edit_message(status_msg, "💿 *در حال دریافت لیست آهنگ‌های آلبوم...*")
        else:
            status_msg = await send_message(bot, chat_id, "💿 *در حال دریافت لیست آهنگ‌های آلبوم...*", show_cancel=True)

        from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks
        collection_data = await get_or_crawl_collection(collection_id)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)

        if not collection_data or not tracks_data or not tracks_data.get("results"):
            await edit_message(status_msg, "❌ خطا در دریافت اطلاعات آلبوم.")
            return

        collection = collection_data["results"][0]
        tracks = [t for t in tracks_data["results"] if t.get("wrapperType") == "track"]
        total_tracks = len(tracks)

        if total_tracks == 0:
            await edit_message(status_msg, "❌ این آلبوم هیچ آهنگی ندارد.")
            return

        album_name = collection.get("collectionName", "نامشخص")
        artist_name = collection.get("artistName", "نامشخص")

        # 2. Start tracking with correct arguments
        download_service.album_tracker.start_download(user_id, collection_id, status_msg, total_tracks, album_name)

        # 3. Add tracks to tracker
        for i, track in enumerate(tracks, 1):
            download_service.album_tracker.add_track(user_id, collection_id, track.get("trackName", "نامشخص"), i)

        # Get high-res cover for tagging
        from utils.helpers import get_high_res_artwork
        artwork_url = get_high_res_artwork(collection.get("artworkUrl100"))
        cover_bytes = await download_service.artwork_service.get_artwork_bytes(collection_id, artwork_url)
        download_service.album_tracker.set_cover_bytes(user_id, collection_id, cover_bytes)

        success_count = 0
        failed_ids = []

        for i, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, collection_id):
                await edit_message(status_msg, f"⏹️ *دانلود آلبوم متوقف شد.*\n\n💿 {album_name}\n🎤 {artist_name}")
                return

            track_id = track.get("trackId")
            track_name = track.get("trackName", "نامشخص")

            status_prefix = download_service.album_tracker.get_progress_text(user_id, collection_id)

            # Update status msg within download_and_send_track by passing it
            status_msg, success = await download_service.download_and_send_track(
                chat_id, track_id, user_id,
                status_msg=status_msg,
                is_batch=True,
                album_cover_bytes=cover_bytes,
                collection_id=collection_id,
                selected_quality=quality,
                track_name_hint=track_name,
                track_index=i,
                status_prefix=status_prefix
            )

            if success:
                success_count += 1
                download_service.album_tracker.update_track_result(user_id, collection_id, track_name, True)
            else:
                failed_ids.append(str(track_id))
                download_service.album_tracker.update_track_result(user_id, collection_id, track_name, False, "Download failed")

            # Avoid flood
            await asyncio.sleep(0.5)

        # Final Summary
        summary = (
            f"🏁 *دانلود آلبوم به پایان رسید*\n\n"
            f"💿 {album_name}\n"
            f"🎤 {artist_name}\n\n"
            f"✅ تعداد موفق: {success_count}\n"
            f"❌ تعداد ناموفق: {len(failed_ids)}"
        )

        markup = []
        if failed_ids:
            markup.append([InlineKeyboardButton(text="🔄 تلاش مجدد قطعات ناموفق", callback_data=f"retry_failed:{','.join(failed_ids)}:u{user_id}")])
            markup.append([InlineKeyboardButton(text="🔄 تلاش مجدد کل آلبوم", callback_data=f"download_album:{collection_id}:u{user_id}")])

        markup.append([create_close_button(user_id)])

        await edit_message(status_msg, summary, reply_markup=InlineKeyboard(*markup))
        download_service.album_tracker.finish_download(user_id, collection_id, success_count, len(failed_ids))

    except Exception as e:
        logger.error(f"Error in download_album: {e}")
        await edit_message(status_msg, f"❌ خطای غیرمنتظره در دانلود آلبوم: {e}")
        download_service.album_tracker.release_lock(user_id, collection_id)
