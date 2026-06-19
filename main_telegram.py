import signal
import sys
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from bot.wrapper import TelegramBotClient, TelegramMessage, TelegramCallbackQuery
from core.config import TELEGRAM_BOT_TOKEN, PROXY
from core.logger import logger
from services import init_services
from bot.handlers import handle_message_logic
from bot.handlers.callbacks import handle_callback
from bot.handlers.broadcast import process_broadcast_message

# Initialize app
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).proxy_url(PROXY).build()
wrapper = TelegramBotClient(application.bot)
services = init_services(wrapper)

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or (msg.from_user and msg.from_user.is_bot): return
    if update.channel_post:
        await process_broadcast_message(wrapper, TelegramMessage(update, context, update.channel_post), services["api_client"])
        return
    if not (msg.text or msg.caption): return
    msg_wrapped = TelegramMessage(update, context)
    await handle_message_logic(wrapper, msg_wrapped, services)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq_wrapped = TelegramCallbackQuery(update, context)
    await handle_callback(wrapper, cq_wrapped, **services)

application.add_handler(MessageHandler(filters.ALL, on_message))
application.add_handler(CallbackQueryHandler(on_callback))

def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("ABRAAVA Telegram bot is starting...")
    application.run_polling()
