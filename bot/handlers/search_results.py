from core.platform import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message
from bot.keyboards import create_close_button
from core.config import PLATFORM, Platform
import logging

logger = logging.getLogger("ABRAAVA:SEARCH_RESULTS")

async def send_search_results(bot, chat_id, type_, term, results, page, search_cache_service, user_id, message_to_edit=None):
    from bot.keyboards import create_pagination_row
    from core.config import ITEMS_PER_PAGE

    total_results = len(results)
    total_pages = (total_results + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_results = results[start_idx:end_idx]

    type_labels = {"track": "آهنگ", "album": "آلبوم", "artist": "هنرمند", "itunes_official": "آیتیونز"}
    text = f"🔍 *نتایج جستجوی {type_labels.get(type_, 'موارد')} برای:* `{term}`\n"
    text += f"صفحه {page} از {total_pages}\n\n"

    markup = []
    for i, res in enumerate(page_results, start_idx + 1):
        name = res.get("trackName") or res.get("collectionName") or res.get("artistName", "نامشخص")
        artist = res.get("artistName", "")
        year = res.get("releaseDate", "")[:4]

        display_name = f"{i}. {name[:30]}"
        if artist: display_name += f" - {artist[:20]}"
        if year: display_name += f" ({year})"

        callback_data = ""
        if type_ == "track" or res.get("wrapperType") == "track":
            callback_data = f"track:{res['trackId']}:u{user_id}"
        elif type_ == "album" or res.get("wrapperType") == "collection":
            callback_data = f"collection:{res['collectionId']}:u{user_id}"
        elif type_ == "artist" or res.get("wrapperType") == "artist":
            callback_data = f"artist:{res['artistId']}:u{user_id}"

        if callback_data:
            markup.append([InlineKeyboardButton(text=display_name, callback_data=callback_data)])

    # Search ID for pagination
    import uuid
    search_id = str(uuid.uuid4())[:8]
    await search_cache_service.set(search_id, {"term": term, "results": results, "type": type_})

    pagination = create_pagination_row(f"page:search:{search_id}:{type_}", page, total_pages, user_id=user_id)
    if pagination: markup.append(pagination)

    markup.append([create_close_button(user_id)])

    if message_to_edit:
        return await edit_message(message_to_edit, text, reply_markup=InlineKeyboard(*markup))
    else:
        return await send_message(bot, chat_id, text, reply_markup=InlineKeyboard(*markup))

async def send_external_search_results(bot, chat_id, type_, term, results, page, search_cache_service, user_id, message_to_edit=None):
    from bot.keyboards import create_pagination_row
    from core.config import ITEMS_PER_PAGE

    total_results = len(results)
    total_pages = (total_results + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_results = results[start_idx:end_idx]

    source_labels = {"ytm": "YouTube Music", "sc": "SoundCloud", "sp": "Spotify"}
    text = f"🔍 *نتایج جستجو در {source_labels.get(type_, 'سرویس خارجی')} برای:* `{term}`\n"
    text += f"صفحه {page} از {total_pages}\n\n"

    markup = []
    for i, res in enumerate(page_results, start_idx + 1):
        name = res.get("trackName", "نامشخص")
        artist = res.get("artistName", "")

        display_name = f"{i}. {name[:35]}"
        if artist: display_name += f" - {artist[:20]}"

        # External IDs usually prefixed like yt_ or sc_
        callback_data = f"track:{res['trackId']}:u{user_id}"
        markup.append([InlineKeyboardButton(text=display_name, callback_data=callback_data)])

    import uuid
    search_id = str(uuid.uuid4())[:8]
    await search_cache_service.set(search_id, {"term": term, "results": {"results": results}, "type": type_})

    pagination = create_pagination_row(f"page:ext_search:{search_id}:{type_}", page, total_pages, user_id=user_id)
    if pagination: markup.append(pagination)

    markup.append([create_close_button(user_id)])

    if message_to_edit:
        return await edit_message(message_to_edit, text, reply_markup=InlineKeyboard(*markup))
    else:
        return await send_message(bot, chat_id, text, reply_markup=InlineKeyboard(*markup))
