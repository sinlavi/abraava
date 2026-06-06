from balethon.objects import InlineKeyboardButton, InlineKeyboard
from core.config import ITEMS_PER_PAGE
from bot.keyboards import create_pagination_row, create_close_button
from utils.messages import send_message, edit_message
from utils.helpers import get_high_res_artwork, format_duration, generate_deep_link
from crawlers.utils import get_or_crawl_artist, get_or_crawl_artist_collections, get_or_crawl_collection, get_or_crawl_collection_tracks, get_track
from crawlers.youtube import get_artist_image
import logging

logger = logging.getLogger("ABRAAVA:DETAILS")

async def show_artist_page(bot, chat_id, artist_id, page, artwork_service, owner_id, message_to_edit=None, force=False, is_pagination=False):
    status_msg = await send_message(bot, chat_id, "🔄 *در حال پردازش اطلاعات هنرمند...*")
    try:
        artist_data = await get_or_crawl_artist(artist_id=artist_id, status_msg=status_msg, force=force)
        if not artist_data or not artist_data.get('results'):
            await edit_message(status_msg, "هنرمند مورد نظر یافت نشد.")
            return

        artist = artist_data['results'][0]
        artist_name = artist.get('artistName', 'نامشخص')
        artist_image = get_artist_image(artist_name)

        text = f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
        text += f"🎭 *سبک:* {artist.get('primaryGenreName', 'نامشخص')}\n"

        collections_data = await get_or_crawl_artist_collections(artist_id)
        collections = collections_data["results"] if collections_data else []

        markup_rows = []
        if collections:
            total_items = len(collections)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))

            page_items = collections[(page-1)*ITEMS_PER_PAGE : page*ITEMS_PER_PAGE]
            text += f"\n📀 *آثار (مجموع {total_items} مورد):*\n"

            for coll in page_items:
                if coll['wrapperType'] == 'collection':
                    year = coll.get('releaseDate', '')[:4]
                    year_str = f" ({year})" if year else ""

                    # Requirement: show all albums, but single-track ones get a track emoji and direct link
                    if coll.get('trackCount') == 1:
                        btn_text = f"🎵 {coll.get('collectionName', 'نامشخص')[:35]}{year_str}"
                        markup_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"single_album:{coll['collectionId']}")])
                    else:
                        btn_text = f"📀 {coll.get('collectionName', 'نامشخص')[:35]}{year_str}"
                        markup_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"collection:{coll['collectionId']}:1")])

            pagination = create_pagination_row(f"artist:{artist_id}", page, total_pages)
            if pagination: markup_rows.append(pagination)

        markup_rows.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:artist:{artist_id}")])

        if is_pagination and message_to_edit and hasattr(message_to_edit, 'photo') and message_to_edit.photo:
            await edit_message(message_to_edit, text, reply_markup=markup_rows)
            await status_msg.delete()
        else:
            artwork_data = await artwork_service.get_artwork_for_display("artist", artist_id, artist_image, owner_id, entity_name=artist_name)
            if artwork_data:
                await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "artist", artist_id, user_id=owner_id)
                await status_msg.delete()
            else:
                await edit_message(status_msg, text, reply_markup=markup_rows)

    except Exception as e:
        logger.error(f"Error in show_artist_page: {e}")
        await edit_message(status_msg, f"خطا در نمایش صفحه هنرمند: {e}")

async def show_collection_page(bot, chat_id, collection_id, page, artwork_service, owner_id, message_to_edit=None, force=False, is_pagination=False):
    status_msg = await send_message(bot, chat_id, "🔄 *در حال پردازش اطلاعات آلبوم...*")
    try:
        collection_data = await get_or_crawl_collection(collection_id, status_msg, force)
        tracks_data = await get_or_crawl_collection_tracks(collection_id)

        if not collection_data or not collection_data.get('results'):
            await edit_message(status_msg, "آلبوم مورد نظر یافت نشد.")
            return

        coll = collection_data['results'][0]
        tracks = tracks_data["results"] if tracks_data else []
        release_date = coll.get('releaseDate', 'نامشخص')[:10]
        artist_name = coll.get('artistName', 'نامشخص')
        artist_id = coll.get('artistId')

        text = f"📀 *نام آلبوم:* {coll.get('collectionName', 'نامشخص')}\n"
        if artist_id: text += f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
        else: text += f"🎤 *نام هنرمند:* {artist_name}\n"

        text += f"📅 *سال انتشار:* {release_date}\n"
        if coll.get('primaryGenreName'): text += f"🎸 *سبک:* {coll.get('primaryGenreName')}\n"
        if coll.get('trackCount'): text += f"🎵 *تعداد قطعات:* {coll.get('trackCount')}\n"

        markup_rows = []
        if tracks:
            total_items = len(tracks)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))

            page_items = tracks[(page-1)*ITEMS_PER_PAGE : page*ITEMS_PER_PAGE]
            text += f"\n🎵 *لیست قطعات:*\n"

            for i, track in enumerate(page_items, (page-1)*ITEMS_PER_PAGE + 1):
                track_num = track.get('trackNumber', i)
                duration = format_duration(track.get('trackTimeMillis', 0))
                text += f"{track_num}. {track.get('trackName', 'نامشخص')} ({duration})\n"

                if track['wrapperType'] == 'track':
                    btn_text = f"🎵 {track_num}. {track.get('trackName', 'نامشخص')[:35]}"
                    markup_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"track:{track['trackId']}")])

            pagination = create_pagination_row(f"collection:{collection_id}", page, total_pages)
            if pagination: markup_rows.append(pagination)

            is_private = (await bot.get_chat(chat_id)).type not in ["group", "supergroup"]
            if is_private:
                markup_rows.append([InlineKeyboardButton(text="⬇️ دانلود کل آلبوم", callback_data=f"download_album:{collection_id}")])

        if artist_id:
            markup_rows.append([InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{artist_id}:1")])

        markup_rows.append([InlineKeyboardButton(text="🔄 تازه‌سازی اطلاعات", callback_data=f"recrawl:collection:{collection_id}")])

        if is_pagination and message_to_edit and hasattr(message_to_edit, 'photo') and message_to_edit.photo:
            await edit_message(message_to_edit, text, reply_markup=markup_rows)
            await status_msg.delete()
        else:
            artwork_url = get_high_res_artwork(coll.get("artworkUrl100"))
            artwork_data = await artwork_service.get_artwork_for_display("collection", collection_id, artwork_url, owner_id)
            if artwork_data:
                await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "collection", collection_id, user_id=owner_id)
                await status_msg.delete()
            else:
                await edit_message(status_msg, text, reply_markup=markup_rows)

    except Exception as e:
        logger.error(f"Error in show_collection_page: {e}")
        await edit_message(status_msg, f"خطا در نمایش صفحه آلبوم: {e}")

async def show_track_page(bot, chat_id, track_id, artwork_service, owner_id, message_to_edit=None):
    status_msg = await send_message(bot, chat_id, "🔄 *در حال بارگذاری اطلاعات آهنگ...*")
    try:
        data = await get_track(track_id, status_msg)
        if not data or not data.get("results"):
            await edit_message(status_msg, "آهنگ مورد نظر یافت نشد.")
            return

        track = data["results"][0]
        duration = format_duration(track.get('trackTimeMillis', 0))
        release_year = track.get("releaseDate", "").split("-")[0] if track.get("releaseDate") else ""
        artist_name = track.get('artistName', 'نامشخص')
        artist_id = track.get('artistId')
        collection_id = track.get('collectionId')
        collection_name = track.get('collectionName', 'نامشخص')

        text = f"🎵 *نام آهنگ:* {track.get('trackName', 'نامشخص')}\n"
        if artist_id: text += f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
        else: text += f"🎤 *نام هنرمند:* {artist_name}\n"

        if collection_id: text += f"💿 *نام آلبوم:* [{collection_name}]({generate_deep_link('collection', collection_id)})\n"
        else: text += f"💿 *نام آلبوم:* {collection_name}\n"

        text += f"⏱️ *مدت زمان:* {duration}\n"
        if release_year: text += f"📅 *سال انتشار:* {release_year}\n"
        if track.get('primaryGenreName'): text += f"🎸 *سبک:* {track.get('primaryGenreName')}\n"
        if track.get('trackExplicitness') == 'explicit': text += f"🔞 *Explicit:* بله\n"

        markup_rows = []
        dl_btns = [InlineKeyboardButton(text="⬇️ دانلود", callback_data=f"download:{track_id}")]
        if track.get("previewUrl"):
            dl_btns.append(InlineKeyboardButton(text="🎧 پیش‌نمایش", callback_data=f"preview:{track_id}"))
        markup_rows.append(dl_btns)

        links = []
        if collection_id: links.append(InlineKeyboardButton(text="📀 مشاهده آلبوم", callback_data=f"collection:{collection_id}:1"))
        if artist_id: links.append(InlineKeyboardButton(text="🎤 مشاهده هنرمند", callback_data=f"artist:{artist_id}:1"))
        if links: markup_rows.append(links)

        artwork_url = get_high_res_artwork(track.get("artworkUrl", track.get("artworkUrl100")))

        artwork_data = await artwork_service.get_artwork_for_display("collection", collection_id or track_id, artwork_url, owner_id)
        if artwork_data:
            await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "collection", collection_id or track_id, user_id=owner_id)
            await status_msg.delete()
        else:
            await edit_message(status_msg, text, reply_markup=markup_rows)

    except Exception as e:
        logger.error(f"Error in show_track_page: {e}")
        await edit_message(status_msg, f"خطا در نمایش صفحه آهنگ: {e}")
