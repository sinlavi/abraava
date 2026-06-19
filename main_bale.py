import signal
import sys
from balethon import Client
from balethon.objects import Message as BaleMessage, CallbackQuery as BaleCallbackQuery
from bot.wrapper import BalethonBotClient, BalethonMessage, BalethonCallbackQuery
from core.config import BOT_TOKEN, PROXY
from core.logger import logger
from services import init_services
from bot.handlers import handle_message_logic
from bot.handlers.callbacks import handle_callback
from bot.handlers.broadcast import process_broadcast_message

bot = Client(BOT_TOKEN, proxy=PROXY)
wrapper = BalethonBotClient(bot)
services = init_services(wrapper)

@bot.on_message()
async def on_message(message: BaleMessage):
    if not message.author or message.author.is_bot: return
    if message.chat.type == "channel":
        await process_broadcast_message(wrapper, BalethonMessage(message, wrapper), services["api_client"])
        return
    if not (message.text or message.caption): return
    msg_wrapped = BalethonMessage(message, wrapper)
    await handle_message_logic(wrapper, msg_wrapped, services)

@bot.on_callback_query()
async def on_callback(callback_query: BaleCallbackQuery):
    cq_wrapped = BalethonCallbackQuery(callback_query, wrapper)
    await handle_callback(wrapper, cq_wrapped, **services)

def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("ABRAAVA Bale bot is starting...")
    bot.run()
