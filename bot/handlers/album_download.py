import asyncio
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks

async def download_album(bot, chat_id, collection_id, user_id, download_service, quality=None):
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

        markup = [[InlineKeyboardButton(text="⏹️ توقف دانلود", callback_data=f"cancel_album:{user_id}:{collection_id}")]]
        await edit_message(parent_msg, f"📀 *آلبوم:* {coll_name}\n🎵 *تعداد قطعات:* {len(tracks)}\n⬇️ *در حال دانلود...*", reply_markup=markup)

        # Get album cover
        album_cover_bytes = await download_service.artwork_service.get_artwork_bytes(coll.get('collectionId'), coll.get('artworkUrl100'))

        settings = await download_service.user_settings_service.get_settings(user_id)
        quality_value = quality or settings.download_quality.value
        if quality_value == "ask": quality_value = "192"

        success_count = 0
        failed_count = 0
        failed_tracks = []

        for idx, track in enumerate(tracks, 1):
            if download_service.album_tracker.is_cancelled(user_id, collection_id):
                break

            try:
                # Update parent message to show which track is being processed
                track_name = track.get('trackName', 'Unknown')
                progress_text = (
                    f"📀 *آلبوم:* {coll_name}\n"
                    f"🎵 *تعداد کل قطعات:* {len(tracks)}\n"
                    f"✅ *موفق:* {success_count}\n"
                    f"❌ *ناموفق:* {failed_count}\n"
                    f"⏳ *در حال پردازش ({idx}/{len(tracks)}):* {track_name}\n"
                    f"⬇️ *در حال دانلود...*"
                )
                prog_markup = [[InlineKeyboardButton(text="⏹️ توقف دانلود", callback_data=f"cancel_album:{user_id}:{collection_id}")]]
                await edit_message(parent_msg, progress_text, reply_markup=InlineKeyboard(*prog_markup))

                # Pass parent_msg to download_service to avoid new message creation
                await download_service.download_and_send_track(
                    chat_id, track['trackId'], user_id,
                    status_msg=parent_msg,
                    is_batch=True, album_cover_bytes=album_cover_bytes,
                    collection_id=collection_id, selected_quality=quality_value,
                    track_name_hint=track.get('trackName'), track_index=idx
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error downloading track {idx} in album: {e}")
                failed_count += 1
                failed_tracks.append((track.get('trackId'), track.get('trackName', 'Unknown')))

            # Update parent message with progress
            progress_text = (
                f"📀 *آلبوم:* {coll_name}\n"
                f"🎵 *تعداد قطعات:* {len(tracks)}\n"
                f"✅ *موفق:* {success_count}\n"
                f"❌ *ناموفق:* {failed_count}\n"
                f"⬇️ *در حال دانلود...*"
            )
            prog_markup = [[InlineKeyboardButton(text="⏹️ توقف دانلود", callback_data=f"cancel_album:{user_id}:{collection_id}")]]
            await edit_message(parent_msg, progress_text, reply_markup=InlineKeyboard(*prog_markup))
            await asyncio.sleep(0.5)

        final_text = f"✅ دانلود آلبوم {coll_name} به پایان رسید.\n🎵 مجموع قطعات: {len(tracks)}\n✅ موفق: {success_count}"
        markup_rows = []
        if failed_count > 0:
            final_text += f"\n❌ ناموفق: {failed_count}\n\n"
            final_text += "📑 *قطعات دانلود نشده:*\n"
            for _, name in failed_tracks:
                final_text += f"🔸 {name}\n"

            failed_ids = ",".join([str(tid) for tid, _ in failed_tracks])
            # If too many failed, we might hit callback data limit, but let's assume it's reasonable
            if len(failed_ids) < 40:
                markup_rows.append([InlineKeyboardButton(text="🔄 تلاش مجدد قطعات ناموفق", callback_data=f"retry_failed:{failed_ids}")])

        markup_rows.append([InlineKeyboardButton(text="🔄 تلاش مجدد کل آلبوم", callback_data=f"download_album:{collection_id}")])

        try: await parent_msg.delete()
        except: pass

        await send_message(bot, chat_id, final_text, reply_markup=InlineKeyboard(*markup_rows))

    finally:
        download_service.album_tracker.finish_download(user_id, collection_id, success_count, failed_count)
