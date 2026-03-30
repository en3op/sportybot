"""
Render.com deployment entry point
Runs Flask dashboard (web) and both bots in background threads
"""

import os
import threading
import logging
import sqlite3
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_databases():
    """Initialize all required databases."""
    # VIP users database
    vip_conn = sqlite3.connect("vip_users.db")
    vip_conn.executescript("""
        CREATE TABLE IF NOT EXISTS vip_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            active INTEGER DEFAULT 1,
            expiry_date TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_type TEXT,
            content TEXT,
            sent_count INTEGER DEFAULT 0,
            sent_date TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    vip_conn.commit()
    vip_conn.close()
    logger.info("vip_users.db initialized")
    
    # Prediction pool database
    pool_conn = sqlite3.connect("prediction_pool.db")
    pool_conn.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            match_date TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            source TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            market TEXT NOT NULL,
            pick TEXT NOT NULL,
            odds REAL NOT NULL,
            confidence REAL NOT NULL,
            risk_tier TEXT NOT NULL,
            reasoning TEXT,
            approved INTEGER DEFAULT 0,
            model_version TEXT DEFAULT 'v2',
            source_data TEXT,
            result TEXT DEFAULT 'pending',
            graded_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );
    """)
    pool_conn.commit()
    pool_conn.close()
    logger.info("prediction_pool.db initialized")

def run_vip_bot():
    """Run VIP bot in background thread with its own event loop."""
    try:
        logger.info("Starting VIP bot thread...")
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        import run_vip_bot
        run_vip_bot.main()
    except Exception as e:
        logger.error(f"VIP bot error: {e}")
    finally:
        if loop.is_running():
            loop.close()

def run_free_bot():
    """Run Free bot in background thread with its own event loop."""
    try:
        logger.info("Starting Free bot thread...")
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        import run_free_bot
        run_free_bot.main()
    except Exception as e:
        logger.error(f"Free bot error: {e}")
    finally:
        if loop.is_running():
            loop.close()

def start_bots():
    """Start both bots in background threads."""
    vip_thread = threading.Thread(target=run_vip_bot, daemon=True)
    vip_thread.start()
    
    free_thread = threading.Thread(target=run_free_bot, daemon=True)
    free_thread.start()
    
    logger.info("Both bots started in background threads")

if __name__ == "__main__":
    # Initialize databases first
    init_databases()
    
    # Start bots in background
    start_bots()
    
    # Run Flask app (this is the main process)
    from app import app
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask dashboard on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
