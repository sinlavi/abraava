from core.platform import InlineKeyboardButton, InlineKeyboard
from utils.messages import send_message, edit_message
from bot.keyboards import create_close_button
from core.logger import logger

async def handle_search(bot, chat_id, user_id, type_, term, api_client, search_cache_service, offline_mode=False):
    if offline_mode:
        await send_message(bot, chat_id, "⚠️ بات در حال حاضر در حالت آفلاین است و فقط آهنگ‌های کش شده قابل دانلود هستند.")
        return

    status_msg = await send_message(bot, chat_id, f"🔍 *در حال جستجوی {term}...*")

    try:
        from crawlers.utils import search_itunes
        results = await search_itunes(term, type_ if type_ != 'itunes_official' else None)

        if not results or not results.get("results"):
            # Fallback to external if it was a general track search
            if type_ == "track":
                await edit_message(status_msg, "🔍 *در آیتیونز یافت نشد، در حال جستجو در یوتیوب...*")
                from crawlers.youtube import search_youtube
                yt_results = await search_youtube(term)
                if yt_results:
                    from bot.handlers.search_results import send_external_search_results
                    await send_external_search_results(bot, chat_id, "ytm", term, yt_results, 1, search_cache_service, user_id, status_msg)
                    return

            await edit_message(status_msg, "❌ موردی یافت نشد.")
            return

        from bot.handlers.search_results import send_search_results
        await send_search_results(bot, chat_id, type_, term, results["results"], 1, search_cache_service, user_id, status_msg)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await edit_message(status_msg, "❌ خطا در جستجو. لطفا دوباره تلاش کنید.")

async def quick_search(bot, chat_id, user_id, term, api_client, user_settings_service, download_service):
    status_msg = await send_message(bot, chat_id, f"⚡ *جستجوی سریع برای:* `{term}`")

    try:
        from crawlers.utils import search_itunes
        results = await search_itunes(term, "track")

        if results and results.get("results"):
            track = results["results"][0]
            track_id = track["trackId"]
            await download_service.download_and_send_track(chat_id, track_id, user_id, status_msg=status_msg)
        else:
            await edit_message(status_msg, "❌ موردی یافت نشد.")
    except Exception as e:
        logger.error(f"Quick search error: {e}")
        await edit_message(status_msg, "❌ خطا در جستجوی سریع.")
