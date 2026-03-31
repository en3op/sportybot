"""Free Bot Runner for Render.com"""
import os
import sys
import logging
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Free Bot - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

async def async_main():
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import free_bot

    token = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", free_bot.cmd_start))
    app.add_handler(CommandHandler("help", free_bot.cmd_help))
    app.add_handler(CommandHandler("analyze", free_bot.cmd_analyze))
    app.add_handler(CommandHandler("search", free_bot.cmd_search))
    app.add_handler(CommandHandler("full", free_bot.cmd_full))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_bot.handle_analyze_text))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, free_bot.handle_photo))

    logger.info("Free bot handlers registered, initializing...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)
    logger.info("Free bot polling started!")
    await asyncio.Event().wait()

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
