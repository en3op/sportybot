"""
Free Bot Runner for PythonAnywhere
Run this as a scheduled task (every hour, but it will keep running)
"""

import os
import sys
import logging

# Set up path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Free Bot - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Free bot...")
    
    # Import and configure bot
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import free_bot
    
    token = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")
    
    app = Application.builder().token(token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", free_bot.cmd_start))
    app.add_handler(CommandHandler("help", free_bot.cmd_help))
    app.add_handler(CommandHandler("vip", free_bot.cmd_vip))
    app.add_handler(MessageHandler(filters.PHOTO, free_bot.handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_bot.handle_message))
    
    logger.info("Free bot handlers registered, starting polling...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
