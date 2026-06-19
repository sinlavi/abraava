from core.config import ITEMS_PER_PAGE, DEEP_LINK_BASE
from bot.keyboards import create_pagination_row, create_close_button
from utils.messages import send_message, edit_message, safe_delete
from utils.helpers import get_high_res_artwork, format_duration, generate_deep_link
from crawlers.utils import get_or_crawl_artist, get_or_crawl_artist_collections, get_or_crawl_collection, get_or_crawl_collection_tracks, get_track, format_artist_hashtag
from crawlers.youtube import get_artist_image
import logging
import asyncio

logger = logging.getLogger("ABRAAVA:DETAILS")

async def show_artist_page(bot, chat_id, artist_id, page, artwork_service, owner_id, message_to_edit=None, force=False, is_pagination=False, reply_to=None):
    if not is_pagination:
        if message_to_edit: status_msg = await edit_message(message_to_edit, "🔄 *در حال پردازش اطلاعات هنرمند...*")
        else: status_msg = await send_message(bot, chat_id, "🔄 *در حال پردازش اطلاعات هنرمند...*", show_cancel=True, reply_to_message_id=reply_to)
    else: status_msg = message_to_edit
    try:
        artist_task, collections_task = asyncio.create_task(get_or_crawl_artist(artist_id=artist_id, force=force)), asyncio.create_task(get_or_crawl_artist_collections(artist_id))
        artist_data, collections_data = await asyncio.gather(artist_task, collections_task)
        if not artist_data or not artist_data.get('results'):
            await edit_message(status_msg, "هنرمند مورد نظر یافت نشد.")
            return
        artist = artist_data['results'][0]
        artist_name = artist.get('artistName', 'نامشخص')
        text = f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
        if artist.get('primaryGenreName'): text += f"🎭 *سبک:* {artist.get('primaryGenreName')}\n"
        hashtags = [f"#{artist.get('primaryGenreName').replace(' ', '_')}"] if artist.get('primaryGenreName') else []
        hashtags.append(format_artist_hashtag(artist_name))
        text += f"{' '.join(hashtags)}\n"
        collections = collections_data["results"] if collections_data else []
        markup_rows = []
        if collections:
            total_items = len(collections)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            page_items = collections[(page-1)*ITEMS_PER_PAGE : page*ITEMS_PER_PAGE]
            text += f"\n📀 *آثار (مجموع {total_items} مورد):*\n"
            for i, coll in enumerate(page_items, (page-1)*ITEMS_PER_PAGE + 1):
                if coll.get('wrapperType') in ['collection', 'track']:
                    year = coll.get('releaseDate', '')[:4]
                    year_str = f" ({year})" if year else ""
                    name = coll.get('collectionName') or coll.get('trackName') or 'نامشخص'
                    try: track_count = int(coll.get('trackCount', 0))
                    except: track_count = 0
                    if coll.get('wrapperType') == 'collection' and track_count > 1:
                        btn_text, callback = f"‎{i}. {name[:35]}{year_str} 📀", f"collection:{coll['collectionId']}:u{owner_id}"
                    else:
                        item_id = coll.get('collectionId') or coll.get('trackId')
                        btn_text, callback = f"‎{i}. {name[:35]}{year_str} 🎵", f"single_album:{item_id}:u{owner_id}"
                    markup_rows.append([{"text": btn_text, "callback_data": callback}])
            pagination = create_pagination_row(f"artist:{artist_id}", page, total_pages, user_id=owner_id)
            if pagination: markup_rows.append(pagination)
        itunes_url = artist.get('artistLinkUrl') or artist.get('artistViewUrl') or f"https://music.apple.com/artist/{artist_id}"
        markup_rows.append([{"text": "🔄 تازه‌سازی", "callback_data": f"recrawl:artist:{artist_id}:u{owner_id}"}, {"text": "📋 کپی پیوند", "copy_text": f"{DEEP_LINK_BASE}artist_{artist_id}"}])
        markup_rows.append([{"text": "🌐 اطلاعات بیشتر", "url": itunes_url}, {"text": "🔍 جستجوی آهنگ‌ها", "callback_data": f"refine:track:{artist_name}:u{owner_id}"}])
        if is_pagination and message_to_edit: await edit_message(message_to_edit, text, reply_markup=markup_rows, force_edit=True)
        else:
            artwork_url = get_high_res_artwork(artist.get("artistImage", get_artist_image(artist_name)))
            artwork_data = await artwork_service.get_artwork_for_display("artist", artist_id, artwork_url, owner_id, entity_name=artist_name)
            if artwork_data:
                await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "artist", artist_id, user_id=owner_id)
                if status_msg: await safe_delete(status_msg)
            else: await edit_message(status_msg, text, reply_markup=markup_rows)
    except Exception as e:
        logger.error(f"Error in show_artist_page: {e}")
        retry_markup = [[{"text": "🔄 تلاش مجدد", "callback_data": f"artist:{artist_id}:1:u{owner_id}"}]]
        if status_msg: await edit_message(status_msg, f"خطا در نمایش صفحه هنرمند: {e}", reply_markup=retry_markup)
        else: await send_message(bot, chat_id, f"خطا در نمایش صفحه هنرمند: {e}", reply_markup=retry_markup)

async def show_collection_page(bot, chat_id, collection_id, page, artwork_service, owner_id, message_to_edit=None, force=False, is_pagination=False, reply_to=None):
    if not is_pagination:
        if message_to_edit: status_msg = await edit_message(message_to_edit, "🔄 *در حال بارگذاری اطلاعات آلبوم...*")
        else: status_msg = await send_message(bot, chat_id, "🔄 *در حال بارگذاری اطلاعات آلبوم...*", show_cancel=True, reply_to_message_id=reply_to)
    else: status_msg = message_to_edit
    try:
        coll_task, tracks_task = asyncio.create_task(get_or_crawl_collection(collection_id, force=force)), asyncio.create_task(get_or_crawl_collection_tracks(collection_id))
        collection_data, tracks_data = await asyncio.gather(coll_task, tracks_task)
        if not collection_data or not collection_data.get("results"):
            await edit_message(status_msg, "آلبوم مورد نظر یافت نشد.")
            return
        coll = collection_data['results'][0]
        tracks = tracks_data["results"] if tracks_data else []
        release_date = coll.get('releaseDate', 'نامشخص')[:10]
        artist_name, artist_id, collection_id = coll.get('artistName', 'نامشخص'), coll.get('artistId'), coll.get('collectionId')
        text = f"📀 *نام آلبوم:* [{coll.get('collectionName', 'نامشخص')}]({generate_deep_link('collection', collection_id)})\n"
        if artist_id: text += f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
        else: text += f"🎤 *نام هنرمند:* {artist_name}\n"
        text += f"📅 *سال انتشار:* {release_date}\n"
        if coll.get('primaryGenreName'): text += f"🎸 *سبک:* {coll.get('primaryGenreName')}\n"
        if coll.get('trackCount'): text += f"🎵 *تعداد قطعات:* {coll.get('trackCount')}\n"
        hashtags = [f"#{release_date[:4]}"] if release_date[:4].isdigit() else []
        if coll.get('primaryGenreName'): hashtags.append(f"#{coll.get('primaryGenreName').replace(' ', '_')}")
        hashtags.append(format_artist_hashtag(artist_name))
        if hashtags: text += f"\n{' '.join(hashtags)}\n"
        markup_rows = []
        if tracks:
            total_items = len(tracks)
            total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            page = max(1, min(page, total_pages))
            page_items = tracks[(page-1)*ITEMS_PER_PAGE : page*ITEMS_PER_PAGE]
            text += f"\n🎵 *لیست قطعات:*\n"
            for i, track in enumerate(page_items, (page-1)*ITEMS_PER_PAGE + 1):
                track_num = track.get('trackNumber', i)
                duration, track_name, track_id = format_duration(track.get('trackTimeMillis', 0)), track.get('trackName', 'نامشخص'), track.get('trackId')
                if track_id: text += f"‎{track_num}. [{track_name}]({generate_deep_link('track', track_id)}) ({duration}) 🎵\n"
                else: text += f"‎{track_num}. {track_name} ({duration}) 🎵\n"
                if track.get('wrapperType') == 'track':
                    markup_rows.append([{"text": f"‎{track_num}. {track_name[:35]} 🎵", "callback_data": f"track:{track['trackId']}:u{owner_id}"}])
            pagination = create_pagination_row(f"collection:{collection_id}", page, total_pages, user_id=owner_id)
            if pagination: markup_rows.append(pagination)
            chat = await bot.get_chat(chat_id)
            if getattr(chat, 'type', 'private') == 'private':
                markup_rows.append([{"text": "⬇️ دانلود کل آلبوم", "callback_data": f"download_album:{collection_id}:u{owner_id}"}])
        if artist_id: markup_rows.append([{"text": "🎤 مشاهده هنرمند", "callback_data": f"artist:{artist_id}:u{owner_id}"}])
        itunes_url = coll.get('collectionViewUrl') or coll.get('viewUrl') or f"https://music.apple.com/album/{collection_id}"
        markup_rows.append([{"text": "🔄 تازه‌سازی", "callback_data": f"recrawl:collection:{collection_id}:u{owner_id}"}, {"text": "📋 کپی پیوند", "copy_text": f"{DEEP_LINK_BASE}collection_{collection_id}"}])
        markup_rows.append([{"text": "🌐 اطلاعات بیشتر", "url": itunes_url}, {"text": "🎤 آثار دیگر هنرمند", "callback_data": f"artist:{artist_id}:u{owner_id}"}])
        if is_pagination and message_to_edit: await edit_message(message_to_edit, text, reply_markup=markup_rows, force_edit=True)
        else:
            artwork_url = get_high_res_artwork(coll.get("artworkUrl100"))
            artwork_data = await artwork_service.get_artwork_for_display("collection", collection_id, artwork_url, owner_id)
            if artwork_data:
                await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "collection", collection_id, user_id=owner_id)
                if status_msg: await safe_delete(status_msg)
            else: await edit_message(status_msg, text, reply_markup=markup_rows)
    except Exception as e:
        logger.error(f"Error in show_collection_page: {e}")
        retry_markup = [[{"text": "🔄 تلاش مجدد", "callback_data": f"collection:{collection_id}:1:u{owner_id}"}]]
        if status_msg: await edit_message(status_msg, f"خطا در نمایش صفحه آلبوم: {e}", reply_markup=retry_markup)
        else: await send_message(bot, chat_id, f"خطا در نمایش صفحه آلبوم: {e}", reply_markup=retry_markup)

async def show_track_page(bot, chat_id, track_id, artwork_service, owner_id, message_to_edit=None, reply_to=None):
    if not message_to_edit: status_msg = await send_message(bot, chat_id, "🔄 *در حال بارگذاری اطلاعات آهنگ...*", show_cancel=True, reply_to_message_id=reply_to)
    else: status_msg = await edit_message(message_to_edit, "🔄 *در حال بارگذاری اطلاعات آهنگ...*")
    try:
        data = await get_track(track_id)
        if not data or not data.get("results"):
            await edit_message(status_msg, "آهنگ مورد نظر یافت نشد.")
            return
        track = data["results"][0]
        duration, release_year = format_duration(track.get('trackTimeMillis', 0)), track.get("releaseDate", "").split("-")[0] if track.get("releaseDate") else ""
        artist_name, artist_id, collection_id, collection_name, track_name = track.get('artistName', 'نامشخص'), track.get('artistId'), track.get('collectionId'), track.get('collectionName', 'نامشخص'), track.get('trackName', 'نامشخص')
        is_sc = str(track_id).startswith("sc_")
        text = f"🎵 *نام آهنگ:* [{track_name}]({generate_deep_link('track', track_id)})\n"
        if is_sc: text += f"🎤 *نام آپلودر:* {artist_name}\n"
        else:
            if artist_id: text += f"🎤 *نام هنرمند:* [{artist_name}]({generate_deep_link('artist', artist_id)})\n"
            else: text += f"🎤 *نام هنرمند:* {artist_name}\n"
            if collection_id: text += f"💿 *نام آلبوم:* [{collection_name}]({generate_deep_link('collection', collection_id)})\n"
            else: text += f"💿 *نام آلبوم:* {collection_name}\n"
            text += f"⏱️ *مدت زمان:* {duration}\n"
        if release_year: text += f"📅 *سال انتشار:* {release_year}\n"
        if track.get('primaryGenreName'): text += f"🎸 *سبک:* {track.get('primaryGenreName')}\n"
        hashtags = [f"#{release_year}"] if release_year else []
        if track.get('primaryGenreName'): hashtags.append(f"#{track.get('primaryGenreName').replace(' ', '_')}")
        hashtags.append(format_artist_hashtag(artist_name))
        if hashtags: text += f"\n{' '.join(hashtags)}\n"
        markup_rows = [[{"text": "⬇️ دانلود", "callback_data": f"download:{track_id}:u{owner_id}"}]]
        if not is_sc and track.get("previewUrl"): markup_rows[0].append({"text": "🎧 پیش‌نمایش", "callback_data": f"preview:{track_id}:u{owner_id}"})
        if not is_sc: markup_rows.append([{"text": "📜 متن آهنگ", "callback_data": f"lyrics:{track_id}:u{owner_id}"}])
        links = []
        if collection_id: links.append({"text": "📀 مشاهده آلبوم", "callback_data": f"collection:{collection_id}:u{owner_id}"})
        if artist_id: links.append({"text": "🎤 مشاهده هنرمند", "callback_data": f"artist:{artist_id}:u{owner_id}"})
        if links: markup_rows.append(links)
        itunes_url = track.get('trackViewUrl') or track.get('viewUrl') or f"https://music.apple.com/song/{track_id}"
        if not str(track_id).startswith(("yt_", "sc_", "sp_")): markup_rows.append([{"text": "📂 نمایش در مینی اپ", "web_app": f"https://3rah.ir/music/ui?id={track_id}"}])
        markup_rows.append([{"text": "📋 کپی پیوند", "copy_text": f"{DEEP_LINK_BASE}track_{track_id}"}, {"text": "🌐 اطلاعات بیشتر", "url": itunes_url}])
        artwork_url = get_high_res_artwork(track.get("artworkUrl", track.get("artworkUrl100")))
        artwork_data = await artwork_service.get_artwork_for_display("collection", (collection_id or track_id) if not is_sc else track_id, artwork_url, owner_id)
        if artwork_data:
            await artwork_service.send_artwork_photo(bot, chat_id, artwork_data, text, markup_rows, "collection", (collection_id or track_id) if not is_sc else track_id, user_id=owner_id)
            if status_msg: await safe_delete(status_msg)
        else: await edit_message(status_msg, text, reply_markup=markup_rows)
    except Exception as e:
        logger.error(f"Error in show_track_page: {e}")
        retry_markup = [[{"text": "🔄 تلاش مجدد", "callback_data": f"track:{track_id}:u{owner_id}"}]]
        if status_msg: await edit_message(status_msg, f"خطا در نمایش صفحه آهنگ: {e}", reply_markup=retry_markup)
        else: await send_message(bot, chat_id, f"خطا در نمایش صفحه آهنگ: {e}", reply_markup=retry_markup)
