"""
VIP Bot Runner for PythonAnywhere
Run this as a scheduled task (every hour, but it will keep running)
"""

import os
import sys
import logging

# Set up path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - VIP Bot - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting VIP bot...")
    
    # Import and configure bot
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import bot
    
    token = os.environ.get("VIP_BOT_TOKEN", "8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk")
    
    app = Application.builder().token(token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("help", bot.cmd_help))
    app.add_handler(CommandHandler("safe", bot.cmd_safe))
    app.add_handler(CommandHandler("optimize", bot.cmd_optimize))
    app.add_handler(CommandHandler("vip", bot.cmd_vip))
    app.add_handler(CommandHandler("admin", bot.cmd_admin))
    app.add_handler(CommandHandler("addvip", bot.cmd_addvip))
    app.add_handler(CommandHandler("removevip", bot.cmd_removevip))
    app.add_handler(CommandHandler("listvip", bot.cmd_listvip))
    app.add_handler(CommandHandler("broadcast", bot.cmd_broadcast))
    app.add_handler(CommandHandler("test", bot.cmd_test))
    app.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    logger.info("VIP bot handlers registered, starting polling...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
