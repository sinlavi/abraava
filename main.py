import os
from core.config import PLATFORM
from core.logger import logger

if __name__ == "__main__":
    if PLATFORM == "telegram":
        from main_telegram import application
        logger.info("Starting Telegram bot...")
        application.run_polling()
    else:
        from main_bale import bot
        logger.info("Starting Bale bot...")
        bot.run()
