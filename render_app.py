"""
Render.com deployment entry point
Runs Flask dashboard (web) and uses multiprocessing for bots
"""

import os
import logging
import sqlite3
import multiprocessing

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

def run_vip_bot_process():
    """Run VIP bot in separate process."""
    logger.info("VIP bot process starting...")
    import subprocess
    import sys
    subprocess.run([sys.executable, "run_vip_bot.py"])

def run_free_bot_process():
    """Run Free bot in separate process."""
    logger.info("Free bot process starting...")
    import subprocess
    import sys
    subprocess.run([sys.executable, "run_free_bot.py"])

def check_tesseract():
    """Verify if Tesseract-OCR is installed and accessible."""
    import shutil
    path = shutil.which("tesseract")
    if path:
        logger.info(f"Tesseract-OCR found at: {path}")
        return True
    else:
        # Check standard Windows path
        if os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
            logger.info("Tesseract-OCR found at standard Windows path")
            return True
        logger.warning("Tesseract-OCR NOT FOUND. Free Bot OCR will fail.")
        return False

if __name__ == "__main__":
    # Initialize databases first
    init_databases()
    
    # Check dependencies
    check_tesseract()
    
    # Start bots as separate processes
    logger.info("Starting bot worker processes...")
    vip_process = multiprocessing.Process(target=run_vip_bot_process, name="VIP-Bot", daemon=True)
    free_process = multiprocessing.Process(target=run_free_bot_process, name="Free-Bot", daemon=True)
    
    vip_process.start()
    free_process.start()
    
    logger.info(f"Bots started! VIP-Bot(PID:{vip_process.pid}), Free-Bot(PID:{free_process.pid})")
    
    # Run Flask app (main process)
    try:
        from app import app
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"Starting Flask dashboard on port {port}")
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        logger.error(f"Flask application failed: {e}")
    finally:
        logger.info("Shutting down orchestrator...")
        if vip_process.is_alive():
            vip_process.terminate()
        if free_process.is_alive():
            free_process.terminate()
