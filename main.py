import os

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import BOT_TOKEN, logger
from handlers import handle_start, handle_message, handle_callback, handle_setting, handle_setlang, handle_scloud, \
    handle_deezer, handle_ytmusic, handle_itunes


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("scloud", handle_scloud))
    app.add_handler(CommandHandler("spotify", handle_deezer))
    app.add_handler(CommandHandler("deezer", handle_deezer))
    app.add_handler(CommandHandler("itunes", handle_itunes))
    app.add_handler(CommandHandler("ytmusic", handle_ytmusic))
    app.add_handler(CommandHandler("setlang", handle_setlang))
    app.add_handler(CommandHandler("setting", handle_setting))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Starting bot polling")
    app.run_polling()


if __name__ == "__main__":
    main()
