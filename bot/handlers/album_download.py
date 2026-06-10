import asyncio
import logging
from balethon.objects import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message, safe_delete
from crawlers.utils import get_or_crawl_collection, get_or_crawl_collection_tracks
from bot.keyboards import create_close_button

logger = logging.getLogger("ABRAAVA:ALBUM_DL")

async def download_album(bot, chat_id, collection_id, user_id, download_service, quality=None, status_msg=None, retry_tracks_info=None):
    if status_msg:
        await safe_delete(status_msg)

    parent_msg = await send_message(bot, chat_id, "⏳ *شروع فرایند دانلود آلبوم...*")

    if not await download_service.album_tracker.acquire_lock(user_id, collection_id):
        await safe_delete(parent_msg)
        parent_msg = await send_message(bot, chat_id, "❌ *در حال حاضر دانلود این آلبوم در حال انجام است*")
        return

    try:
        collection_data = await get_or_crawl_collection(collection_id)
        if retry_tracks_info:
            tracks = retry_tracks_info
        else:
            tracks_data = await get_or_crawl_collection_tracks(collection_id)
            tracks = tracks_data['results'] if tracks_data else []

        if not collection_data or not tracks:
            await safe_delete(parent_msg)
            parent_msg = await send_message(bot, chat_id, "❌ اطلاعات آلبوم یافت نشد")
            return

        coll = collection_data['results'][0]
        coll_name = coll.get('collectionName', 'آلبوم')

        album_markup = InlineKeyboard(*[[InlineKeyboardButton(text="⏹️ توقف دانلود", callback_data=f"cancel_album:{collection_id}:u{user_id}")]])
        await safe_delete(parent_msg)
        parent_msg = await send_message(bot, chat_id, f"📀 *آلبوم:* {coll_name}\n🎵 *تعداد قطعات:* {len(tracks)}\n⬇️ *در حال دانلود...*", reply_markup=album_markup)

        # Log download start - MUST be after the final parent_msg is created so tracker has correct reference
        download_service.album_tracker.start_download(user_id, collection_id, parent_msg, len(tracks), coll_name)

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
                # Add all remaining tracks as failed
                for remaining_track in tracks[idx-1:]:
                    failed_count += 1
                    failed_tracks.append((remaining_track.get('trackId'), remaining_track.get('trackName', 'Unknown')))
                break

            track_name = track.get('trackName', 'Unknown')
            track_id = track.get('trackId')
            progress_prefix = (
                f"📀 *آلبوم:* {coll_name}\n"
                f"📊 *وضعیت:* {idx}/{len(tracks)} قطعه\n"
                f"✅ *موفق:* {success_count}   \n❌ *ناموفق:* {failed_count}\n"
                f"⏳ *در حال پردازش:* {track_name}"
            )

            try:
                # Pass parent_msg to download_service to avoid new message creation
                parent_msg, success = await download_service.download_and_send_track(
                    chat_id, track_id, user_id,
                    status_msg=parent_msg,
                    is_batch=True, album_cover_bytes=album_cover_bytes,
                    collection_id=collection_id, selected_quality=quality_value,
                    track_name_hint=track_name, track_index=idx,
                    status_prefix=progress_prefix,
                    reply_markup=album_markup
                )

                if success is True:
                    success_count += 1
                elif isinstance(success, tuple) and success[0] == "size_limit":
                    failed_count += 1
                    best_q = success[1]
                    reason = f"حجم بیش از ۲۰ مگابایت (پیشنهاد: {best_q})" if best_q else "حجم بیش از ۲۰ مگابایت"
                    failed_tracks.append((track_id, f"{track_name} ({reason})"))
                    # Inform and ask for this specific track
                    if best_q:
                        ask_text = f"⚠️ *حجم آهنگ «{track_name}» بیش از ۲۰ مگابایت است.*\n\nآیا مایلید این قطعه را با کیفیت {best_q} kbps دریافت کنید؟"
                        ask_markup = [[InlineKeyboardButton(text=f"✅ دانلود با کیفیت {best_q}", callback_data=f"dl_low_q:{best_q}:{track_id}:u{user_id}")]]
                        await send_message(bot, chat_id, ask_text, reply_markup=InlineKeyboard(*ask_markup))
                    else:
                        await send_message(bot, chat_id, f"❌ *حجم آهنگ «{track_name}» حتی با کمترین کیفیت هم بیش از ۲۰ مگابایت است.*")
                else:
                    failed_count += 1
                    failed_tracks.append((track_id, track_name))

                # After each track, resend the status message to keep it at the bottom
                if parent_msg:
                    text = parent_msg.text
                    markup = parent_msg.reply_markup
                    await safe_delete(parent_msg)
                    parent_msg = await send_message(bot, chat_id, text, reply_markup=markup)

            except Exception as e:
                logger.error(f"Error downloading track {idx} in album: {e}")
                failed_count += 1
                failed_tracks.append((track_id, track_name))
                if parent_msg:
                    await safe_delete(parent_msg)
                    parent_msg = await send_message(bot, chat_id, progress_prefix, reply_markup=album_markup)

            await asyncio.sleep(0.3)

        await _send_final_summary(bot, chat_id, coll_name, len(tracks), success_count, failed_count, failed_tracks, user_id, collection_id, parent_msg, download_service.album_tracker.is_cancelled(user_id, collection_id))

    finally:
        download_service.album_tracker.finish_download(user_id, collection_id, success_count, failed_count)


async def _send_final_summary(bot, chat_id, coll_name, total_tracks, success_count, failed_count, failed_tracks, user_id, collection_id, parent_msg, is_cancelled):
    if is_cancelled:
        final_text = f"⏹️ *دانلود آلبوم {coll_name} متوقف شد.*\n\n"
    else:
        final_text = f"🏁 *فرایند دانلود آلبوم به پایان رسید!*\n\n"

    final_text += (
        f"💿 *آلبوم:* {coll_name}\n"
        f"🎵 *مجموع قطعات:* {total_tracks}\n"
        f"✅ *موفق:* {success_count}\n"
    )

    markup_rows = []
    if failed_count > 0:
        final_text += f"❌ *ناموفق:* {failed_count}\n\n"
        final_text += "📑 *لیست قطعات دانلود نشده:*\n"
        for _, name in failed_tracks[:15]: # Limit to avoid huge message
            final_text += f"🔸 {name}\n"
        if len(failed_tracks) > 15:
            final_text += f"و {len(failed_tracks) - 15} مورد دیگر...\n"

        failed_ids = ",".join([str(tid) for tid, _ in failed_tracks])
        # In Bale callback data limit might be generous, but let's be careful.
        # We store the IDs in the callback.
        markup_rows.append([InlineKeyboardButton(text="🔄 تلاش مجدد قطعات ناموفق", callback_data=f"retry_failed:{collection_id}:{failed_ids}:u{user_id}")])

    markup_rows.append([create_close_button(user_id)])

    await safe_delete(parent_msg)
    await send_message(bot, chat_id, final_text, reply_markup=InlineKeyboard(*markup_rows))
