# bot.py
import logging
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters
from handlers import handle_message, handle_callback
from config import TOKEN

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)

def main():
    logging.info("Starting bot...")
    app = ApplicationBuilder().token(TOKEN).build()

    # Handle messages from user
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Handle inline button clicks
    app.add_handler(CallbackQueryHandler(handle_callback))

    logging.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
