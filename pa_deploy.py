"""
SportyBot - PythonAnywhere Deployment Script
============================================
This script is designed to run on PythonAnywhere using scheduled tasks.

Setup Instructions:
1. Create a PythonAnywhere account (free tier)
2. Go to "Web" tab and create a new web app (for Flask dashboard)
3. Go to "Tasks" tab and create scheduled tasks for bots:
   - Task 1: python /home/yourusername/sportybot/run_vip_bot.py (Every hour)
   - Task 2: python /home/yourusername/sportybot/run_free_bot.py (Every hour)
4. Set environment variables in .env file or PythonAnywhere dashboard
"""

import os
import sys
import logging
import time
import signal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check if required environment variables are set."""
    required = ["VIP_BOT_TOKEN", "FREE_BOT_TOKEN"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        logger.warning(f"Missing environment variables: {missing}")
        return False
    return True

if __name__ == "__main__":
    logger.info("SportyBot PythonAnywhere deployment ready")
    logger.info("Run the following scripts separately:")
    logger.info("  - run_vip_bot.py (for VIP bot)")
    logger.info("  - run_free_bot.py (for Free bot)")
    logger.info("  - app.py (for Flask dashboard)")
