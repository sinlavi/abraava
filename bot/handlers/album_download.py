import asyncio
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks

async def download_album(bot, chat_id, collection_id, user_id, download_service):
    success_count = 0
    failed_count = 0
    status_msg = await send_message(bot, chat_id, "⏳ *در حال آماده‌سازی دانلود آلبوم...*")

    if not await download_service.album_tracker.acquire_lock(user_id, collection_id):
        await edit_message(status_msg, "❌ *در حال حاضر دانلود این آلبوم در حال انجام است*")
        return

    try:
        collection_data = await get_or_crawl_collection(collection_id, status_msg)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)

        if not collection_data or not tracks_data:
            await edit_message(status_msg, "❌ اطلاعات آلبوم یافت نشد")
            return

        coll = collection_data['results'][0]
        tracks = tracks_data['results']
        coll_name = coll.get('collectionName', 'آلبوم')

        download_service.album_tracker.start_download(user_id, collection_id, status_msg, len(tracks), coll_name)

        for idx, track in enumerate(tracks, 1):
            download_service.album_tracker.add_track(user_id, collection_id, track.get('trackName', 'Unknown'), idx)

        cancel_markup = [[InlineKeyboardButton(text="❌ لغو دانلود آلبوم", callback_data=f"cancel_album:{user_id}:{collection_id}")]]

        # Get album cover
        album_cover_bytes = await download_service.artwork_service.get_artwork_bytes(coll.get('collectionId'), coll.get('artworkUrl100'))

        settings = await download_service.user_settings_service.get_settings(user_id)
        quality_value = settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        for idx, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, collection_id):
                break

            track_name = track.get('trackName', 'Unknown')
            progress = download_service.album_tracker.get_progress_text(user_id, collection_id)
            await edit_message(status_msg, progress, reply_markup=cancel_markup, no_close=True)

            can_dl, wait = await download_service.download_rate_limiter.can_download(user_id, quality_value)
            if not can_dl:
                download_service.album_tracker.update_track_result(user_id, collection_id, track_name, False, f"Rate limit: {wait}s")
                failed_count += 1
                break

            try:
                # We pass is_batch=True to avoid sending individual status messages
                await download_service.download_and_send_track(chat_id, track['trackId'], user_id, status_msg,
                                                            is_batch=True, album_cover_bytes=album_cover_bytes,
                                                            collection_id=collection_id, selected_quality=quality_value)
                download_service.album_tracker.update_track_result(user_id, collection_id, track_name, True)
                success_count += 1
            except Exception:
                download_service.album_tracker.update_track_result(user_id, collection_id, track_name, False, "Error")
                failed_count += 1

            await asyncio.sleep(0.5)

        final_text = f"✅ دانلود آلبوم {coll_name} به پایان رسید.\n🎵 مجموع قطعات: {len(tracks)}\n✅ موفق: {success_count}\n❌ ناموفق: {failed_count}"
        await send_message(bot, chat_id, final_text)

    finally:
        download_service.album_tracker.finish_download(user_id, collection_id, success_count, failed_count)
