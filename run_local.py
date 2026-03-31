"""
SportyBot Local Launcher
========================
Runs all services locally without Render.
Spawns Free bot, VIP bot, and Flask dashboard as subprocesses.

Usage:
    python run_local.py
"""

import os
import sys
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/local_launcher.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent
LOGS_DIR = PROJECT_DIR / "logs"

processes = []


def setup_logs_dir():
    LOGS_DIR.mkdir(exist_ok=True)


def log_to_file(service_name: str):
    log_path = LOGS_DIR / f"{service_name}.log"
    return open(log_path, "a", encoding="utf-8")


def start_service(name: str, command: list, env: dict = None):
    logger.info(f"Starting {name}...")
    
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    
    log_file = log_to_file(name)
    log_file.write(f"\n{'='*60}\n")
    log_file.write(f"Started at {datetime.now()}\n")
    log_file.write(f"{'='*60}\n")
    log_file.flush()
    
    process = subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        env=process_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    
    processes.append({
        "name": name,
        "process": process,
        "log_file": log_file,
    })
    
    logger.info(f"{name} started (PID: {process.pid})")
    return process


def stop_all_services(signum=None, frame=None):
    logger.info("Stopping all services...")
    
    for svc in processes:
        name = svc["name"]
        proc = svc["process"]
        log_file = svc["log_file"]
        
        logger.info(f"Stopping {name} (PID: {proc.pid})...")
        
        try:
            proc.terminate()
            proc.wait(timeout=5)
            logger.info(f"{name} stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning(f"{name} didn't stop, killing...")
            proc.kill()
            proc.wait()
            logger.info(f"{name} killed")
        except Exception as e:
            logger.error(f"Error stopping {name}: {e}")
        finally:
            if log_file and not log_file.closed:
                log_file.write(f"\nStopped at {datetime.now()}\n")
                log_file.close()
    
    logger.info("All services stopped")


def check_tesseract():
    tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    
    for path in tesseract_paths:
        if os.path.exists(path):
            logger.info(f"Tesseract found at: {path}")
            return path
    
    logger.warning("Tesseract not found! OCR features will not work.")
    logger.warning("Install from: https://github.com/UB-Mannheim/tesseract/wiki")
    return None


def main():
    setup_logs_dir()
    
    logger.info("=" * 60)
    logger.info("SportyBot Local Launcher")
    logger.info("=" * 60)
    
    tesseract_path = check_tesseract()
    
    env_vars = {}
    if tesseract_path:
        env_vars["TESSERACT_CMD"] = tesseract_path
    
    try:
        start_service("free_bot", [sys.executable, "free_bot.py"], env_vars)
        time.sleep(2)
        
        start_service("vip_bot", [sys.executable, "bot.py"], env_vars)
        time.sleep(2)
        
        start_service("flask_dashboard", [sys.executable, "app.py"], env_vars)
        
        logger.info("=" * 60)
        logger.info("All services started!")
        logger.info("Free Bot: Polling Telegram")
        logger.info("VIP Bot: Polling Telegram")
        logger.info("Dashboard: http://localhost:5000")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C to stop all services")
        
        signal.signal(signal.SIGINT, stop_all_services)
        signal.signal(signal.SIGTERM, stop_all_services)
        
        while True:
            for svc in processes:
                proc = svc["process"]
                if proc.poll() is not None:
                    logger.error(f"{svc['name']} exited unexpectedly with code {proc.returncode}")
            
            time.sleep(5)
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        stop_all_services()


if __name__ == "__main__":
    main()
