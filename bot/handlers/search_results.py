from balethon.objects import InlineKeyboardButton, InlineKeyboard
from core.config import ITEMS_PER_PAGE
from bot.keyboards import create_pagination_row, create_close_button
from utils.messages import send_message, edit_message
from utils.helpers import generate_search_hash

async def send_search_results(bot, chat_id, type_, term, results, page, search_cache_service, owner_id, message_to_edit=None):
    results_list = results["results"]
    total_items = len(results_list)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = results_list[start_idx:end_idx]

    type_fa_map = {"artist": "هنرمند", "collection": "آلبوم", "track": "آهنگ"}

    header = f"📋 *نتایج جستجو برای {type_fa_map.get(type_, type_)}: {term}*\nتعداد کل: {total_items} مورد"

    markup_rows = []
    for i, item in enumerate(page_items, start_idx + 1):
        wrapper = item.get("wrapperType")
        if wrapper == "artist":
            btn_text = f"🎤 \u200e{i}. {item.get('artistName', 'نامشخص')}"
            callback = f"artist:{item['artistId']}"
        elif wrapper == "collection":
            btn_text = f"📀 \u200e{i}. {item.get('collectionName', 'نامشخص')[:40]} - {item.get('artistName', 'نامشخص')[:30]}"
            callback = f"collection:{item['collectionId']}"
        elif wrapper == "track":
            btn_text = f"🎵 \u200e{i}. {item.get('trackName', 'نامشخص')[:40]} - {item.get('artistName', 'نامشخص')[:30]}"
            callback = f"track:{item['trackId']}"
        else:
            continue
        markup_rows.append([InlineKeyboardButton(text=btn_text, callback_data=callback)])

    if total_pages > 1:
        search_id = generate_search_hash(type_, term)
        await search_cache_service.store(search_id, type_, term, results, owner_id)
        pagination = create_pagination_row(f"page:search:{search_id}:{type_}", page, total_pages)
        if pagination:
            markup_rows.append(pagination)

    markup_rows.append([
        InlineKeyboardButton(text="🔍 آلبوم‌ها", callback_data=f"refine:album:{term}"),
        InlineKeyboardButton(text="🔍 هنرمندان", callback_data=f"refine:artist:{term}"),
        InlineKeyboardButton(text="🔍 آهنگ‌ها", callback_data=f"refine:track:{term}")
    ])

    if message_to_edit:
        await edit_message(message_to_edit, header, reply_markup=markup_rows, force_edit=True)
    else:
        await send_message(bot, chat_id, header, reply_markup=markup_rows)
