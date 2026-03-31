import os
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

    users_conn = sqlite3.connect("users.db")
    users_conn.executescript("""
        CREATE TABLE IF NOT EXISTS free_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            total_interactions INTEGER DEFAULT 0,
            total_slips_analyzed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS vip_upgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            upgraded_at TEXT DEFAULT (datetime('now')),
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (user_id) REFERENCES free_users(user_id)
        );
        CREATE TABLE IF NOT EXISTS interaction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES free_users(user_id)
        );
    """)
    users_conn.commit()
    users_conn.close()
    logger.info("users.db initialized")

    users_conn = sqlite3.connect("users.db")
    users_conn.executescript("""
        CREATE TABLE IF NOT EXISTS free_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            total_interactions INTEGER DEFAULT 0,
            total_slips_analyzed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS vip_upgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            upgraded_at TEXT DEFAULT (datetime('now')),
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (user_id) REFERENCES free_users(user_id)
        );
        CREATE TABLE IF NOT EXISTS interaction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES free_users(user_id)
        );
    """)
    users_conn.commit()
    users_conn.close()
    logger.info("users.db initialized")

FREE_BOT_TOKEN = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")
WEBHOOK_URL = "https://sportybot-v2.onrender.com/telegram-webhook"

free_bot_app = None

def setup_free_bot():
    """Set up the Free bot application."""
    global free_bot_app
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import free_bot

    free_bot_app = Application.builder().token(FREE_BOT_TOKEN).build()

    free_bot_app.add_handler(CommandHandler("start", free_bot.cmd_start))
    free_bot_app.add_handler(CommandHandler("help", free_bot.cmd_help))
    free_bot_app.add_handler(CommandHandler("analyze", free_bot.cmd_analyze))
    free_bot_app.add_handler(CommandHandler("search", free_bot.cmd_search))
    free_bot_app.add_handler(CommandHandler("full", free_bot.cmd_full))
    free_bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_bot.handle_analyze_text))
    free_bot_app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, free_bot.handle_photo))

    logger.info("Free bot handlers registered")

async def set_webhook():
    """Set the webhook for the bot."""
    await free_bot_app.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

async def init_bot_async():
    """Initialize the bot application asynchronously."""
    await free_bot_app.initialize()
    await free_bot_app.start()
    try:
        await set_webhook()
    except Exception as e:
        logger.warning(f"Failed to set webhook (non-critical): {e}")

def init_bot():
    """Initialize the bot synchronously."""
    setup_free_bot()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_bot_async())
    logger.info("Free bot initialized with webhook")

if __name__ == "__main__":
    init_databases()
    init_bot()

    from app import app as flask_app
    
    flask_app.config['TELEGRAM_BOT_APP'] = free_bot_app

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask dashboard on port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
