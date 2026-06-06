import asyncio
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks

async def download_album(bot, chat_id, collection_id, user_id, download_service):
    # This message stays static (no edit) as per request
    parent_msg = await send_message(bot, chat_id, "⏳ *شروع فرایند دانلود آلبوم...*")

    if not await download_service.album_tracker.acquire_lock(user_id, collection_id):
        await edit_message(parent_msg, "❌ *در حال حاضر دانلود این آلبوم در حال انجام است*")
        return

    try:
        collection_data = await get_or_crawl_collection(collection_id)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)

        if not collection_data or not tracks_data:
            await edit_message(parent_msg, "❌ اطلاعات آلبوم یافت نشد")
            return

        coll = collection_data['results'][0]
        tracks = tracks_data['results']
        coll_name = coll.get('collectionName', 'آلبوم')

        # Log download start
        download_service.album_tracker.start_download(user_id, collection_id, parent_msg, len(tracks), coll_name)

        await edit_message(parent_msg, f"📀 *آلبوم:* {coll_name}\n🎵 *تعداد قطعات:* {len(tracks)}\n⬇️ *در حال دانلود...*")

        # Get album cover
        album_cover_bytes = await download_service.artwork_service.get_artwork_bytes(coll.get('collectionId'), coll.get('artworkUrl100'))

        settings = await download_service.user_settings_service.get_settings(user_id)
        quality_value = settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        success_count = 0
        failed_count = 0

        for idx, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, collection_id):
                break

            # Each track download gets its own status message that gets deleted upon completion
            await download_service.download_and_send_track(
                chat_id, track['trackId'], user_id,
                is_batch=True, album_cover_bytes=album_cover_bytes,
                collection_id=collection_id, selected_quality=quality_value,
                track_name_hint=track.get('trackName'), track_index=idx
            )
            success_count += 1
            await asyncio.sleep(0.5)

        await send_message(bot, chat_id, f"✅ دانلود آلبوم {coll_name} به پایان رسید.\n🎵 مجموع قطعات: {len(tracks)}\n✅ موفق: {success_count}")

    finally:
        download_service.album_tracker.finish_download(user_id, collection_id, success_count, failed_count)
