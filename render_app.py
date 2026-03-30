"""
Render.com deployment entry point
Runs Flask dashboard (web) and both bots in background threads
"""

import os
import threading
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_vip_bot():
    """Run VIP bot in background thread."""
    try:
        logger.info("Starting VIP bot thread...")
        import run_vip_bot
        run_vip_bot.main()
    except Exception as e:
        logger.error(f"VIP bot error: {e}")

def run_free_bot():
    """Run Free bot in background thread."""
    try:
        logger.info("Starting Free bot thread...")
        import run_free_bot
        run_free_bot.main()
    except Exception as e:
        logger.error(f"Free bot error: {e}")

def start_bots():
    """Start both bots in background threads."""
    vip_thread = threading.Thread(target=run_vip_bot, daemon=True)
    vip_thread.start()
    
    free_thread = threading.Thread(target=run_free_bot, daemon=True)
    free_thread.start()
    
    logger.info("Both bots started in background threads")

if __name__ == "__main__":
    # Start bots in background
    start_bots()
    
    # Run Flask app (this is the main process)
    from app import app
    import os
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask dashboard on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
