"""
Combined bot runner for PythonAnywhere deployment.
Runs both VIP bot and Free bot in separate threads.
"""

import asyncio
import threading
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_vip_bot():
    """Run the VIP bot in a separate thread."""
    try:
        logger.info("Starting VIP bot...")
        import bot
        # Import and run the bot's main loop
        from telegram.ext import Application
        app = Application.builder().token(os.environ.get("VIP_BOT_TOKEN", "8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk")).build()
        
        # Import handlers from bot.py
        from bot import (
            cmd_start, cmd_help, cmd_safe, cmd_optimize, cmd_vip,
            cmd_admin, cmd_addvip, cmd_removevip, cmd_listvip,
            cmd_broadcast, cmd_test, handle_photo, handle_message
        )
        from telegram.ext import CommandHandler, MessageHandler, filters
        
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("safe", cmd_safe))
        app.add_handler(CommandHandler("optimize", cmd_optimize))
        app.add_handler(CommandHandler("vip", cmd_vip))
        app.add_handler(CommandHandler("admin", cmd_admin))
        app.add_handler(CommandHandler("addvip", cmd_addvip))
        app.add_handler(CommandHandler("removevip", cmd_removevip))
        app.add_handler(CommandHandler("listvip", cmd_listvip))
        app.add_handler(CommandHandler("broadcast", cmd_broadcast))
        app.add_handler(CommandHandler("test", cmd_test))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"VIP bot error: {e}")

def run_free_bot():
    """Run the Free bot in a separate thread."""
    try:
        logger.info("Starting Free bot...")
        import free_bot
        from telegram.ext import Application
        
        app = Application.builder().token(os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")).build()
        
        # Import handlers from free_bot.py
        from free_bot import (
            cmd_start, cmd_help, cmd_vip, handle_photo, handle_message
        )
        from telegram.ext import CommandHandler, MessageHandler, filters
        
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("vip", cmd_vip))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Free bot error: {e}")

if __name__ == "__main__":
    logger.info("Starting combined bot runner...")
    
    # Start VIP bot in thread
    vip_thread = threading.Thread(target=run_vip_bot, daemon=True)
    vip_thread.start()
    
    # Start Free bot in thread  
    free_thread = threading.Thread(target=run_free_bot, daemon=True)
    free_thread.start()
    
    logger.info("Both bots started. Press Ctrl+C to stop.")
    
    # Keep main thread alive
    try:
        while True:
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
