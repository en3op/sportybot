"""VIP Bot Runner for Render.com"""
import os
import sys
import logging
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - VIP Bot - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

async def async_main():
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import bot

    token = os.environ.get("VIP_BOT_TOKEN", "8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("safe", bot.cmd_safe))
    app.add_handler(CommandHandler("optimize", bot.cmd_optimize))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("addvip", bot.cmd_addvip))
    app.add_handler(CommandHandler("removevip", bot.cmd_removevip))
    app.add_handler(CommandHandler("listvip", bot.cmd_listvip))
    app.add_handler(CommandHandler("refresh", bot.cmd_refresh))
    app.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))

    logger.info("VIP bot handlers registered, initializing...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)
    logger.info("VIP bot polling started!")
    await asyncio.Event().wait()

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
