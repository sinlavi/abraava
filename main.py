from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from config import BOT_TOKEN, logger
from handlers import handle_start, handle_message, handle_callback, handle_setlang
from i18 import translate


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("setlang", handle_setlang))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Starting bot polling")
    app.run_polling()


if __name__ == "__main__":
    main()


async def handle_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /setlang <language_code>")
        return

    lang_code = context.args[0].lower()
    supported_languages = ["en", "fa"]  # Add more supported languages as needed

    if lang_code not in supported_languages:
        await update.message.reply_text(f"Unsupported language. Supported languages: {', '.join(supported_languages)}")
        return

    context.user_data["lang"] = lang_code
    await update.message.reply_text(translate("start", lang_code))