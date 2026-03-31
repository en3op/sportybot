"""
SportyBot - Free Betting Slip Analyzer Telegram Bot
====================================================
Users send their betting slip as text. The bot:
  1. Extracts match names from text
  2. Searches live form/stats data via DuckDuckGo
  3. Analyzes picks with AI (NVIDIA NIM API)
  4. Returns 3 slip tiers (SAFE/MODERATE/HIGH)
  5. Limited to 5 free tries, then prompts VIP upgrade

Usage:
    pip install -r requirements.txt
    python free_bot.py
"""

import os
import re
import sqlite3
import logging
import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest

from slip_analyzer.search_analyzer import analyze_slip_with_search

# =============================================================================
# CONFIGURATION
# =============================================================================

BOT_TOKEN = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")
PAYSTACK_LINK = os.environ.get("PAYSTACK_LINK", "https://paystack.com/pay/YOUR_PAYMENT_LINK_HERE")
VIP_BOT_USERNAME = "@Sporty_vip_bot"
MAX_FREE_TRIES = 5

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# =============================================================================
# USER TRACKING & FREE TRIES
# =============================================================================

def _init_users_db():
    """Initialize the users database."""
    conn = sqlite3.connect("users.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS free_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            total_interactions INTEGER DEFAULT 0,
            total_slips_analyzed INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interaction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn

def _track_user(user_id, username=None, first_name=None, last_name=None, action=None, details=None):
    """Track a user interaction in the database."""
    conn = _init_users_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO free_users (user_id, username, first_name, last_name, first_seen, last_seen, total_interactions, total_slips_analyzed)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            last_seen = ?,
            username = COALESCE(?, username),
            first_name = COALESCE(?, first_name),
            last_name = COALESCE(?, last_name),
            total_interactions = total_interactions + 1
    """, (user_id, username, first_name, last_name, now, now, now, username, first_name, last_name))
    if action:
        conn.execute(
            "INSERT INTO interaction_log (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details)
        )
    conn.commit()
    conn.close()

def _track_slip_analyzed(user_id, details=None):
    """Track that a user analyzed a slip."""
    conn = _init_users_db()
    conn.execute(
        "UPDATE free_users SET total_slips_analyzed = total_slips_analyzed + 1, last_seen = datetime('now') WHERE user_id = ?",
        (user_id,)
    )
    conn.execute(
        "INSERT INTO interaction_log (user_id, action, details) VALUES (?, ?, ?)",
        (user_id, "slip_analyzed", details)
    )
    conn.commit()
    conn.close()

def _get_slip_count(user_id: int) -> int:
    """Get how many slips a user has analyzed."""
    conn = _init_users_db()
    row = conn.execute(
        "SELECT total_slips_analyzed FROM free_users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0

def _check_free_limit(user_id: int) -> bool:
    """Check if user has exceeded free limit. Returns True if allowed."""
    count = _get_slip_count(user_id)
    return count < MAX_FREE_TRIES

# =============================================================================
# HELPERS
# =============================================================================

async def _ensure_private(update: Update) -> bool:
    """Only allow private chats."""
    if update.effective_chat and update.effective_chat.type != "private":
        await update.message.reply_text("\u274c This bot only works in private chats.")
        return False
    return True

async def _safe_edit(msg, text: str) -> None:
    """Safely edit a message, handling if it was deleted."""
    try:
        await msg.edit_text(text)
    except BadRequest:
        pass

def _vip_upgrade_message() -> str:
    """Message prompting user to upgrade to VIP."""
    return (
        f"🔒 *Free Limit Reached*\n\n"
        f"You've used all {MAX_FREE_TRIES} free analyses!\n\n"
        f"Upgrade to VIP for:\n"
        f"✅ Unlimited slip analysis\n"
        f"✅ AI-powered 3-tier slips (SAFE/MODERATE/HIGH)\n"
        f"✅ Live odds from SportyBet\n"
        f"✅ Daily premium picks\n"
        f"✅ Only ₦500/week\n\n"
        f"👉 Tap here to start: {VIP_BOT_USERNAME}"
    )

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start."""
    if not await _ensure_private(update):
        return
    user = update.effective_user
    username = user.first_name or "there"
    _track_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        action="/start"
    )
    slip_count = _get_slip_count(user.id)
    remaining = MAX_FREE_TRIES - slip_count
    
    welcome = (
        f"Welcome to SportyBot Free, {username}!\n\n"
        f"I analyze your betting slips and return 3 optimized slips:\n"
        f"🔒 SAFE — Low risk, high probability\n"
        f"⚖️ MODERATE — Balanced risk/reward\n"
        f"🚀 HIGH — High risk, high reward\n\n"
        f"How to use:\n"
        f"1. Send your betting slip as text\n"
        f"2. I search for live form/stats for each match\n"
        f"3. I return 3 optimized slip tiers\n\n"
        f"Example:\n"
        f"`Man City vs Arsenal @1.85`\n"
        f"`Liverpool vs Chelsea @2.10`\n\n"
        f"📊 Free tries remaining: {remaining}/{MAX_FREE_TRIES}\n\n"
        f"Type /help for more details."
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    if not await _ensure_private(update):
        return
    user = update.effective_user
    slip_count = _get_slip_count(user.id)
    remaining = MAX_FREE_TRIES - slip_count
    
    help_text = (
        "*How to Use SportyBot Free*\n\n"
        "*Commands:*\n"
        "/start - Welcome message\n"
        "/analyze - Analyze a betting slip from text\n"
        "/search - Search-based analysis mode\n"
        "/help - This help message\n"
        "/vip - Upgrade to VIP for unlimited analysis\n\n"
        "*Sending a Betting Slip:*\n"
        "1. Type /analyze and paste your picks\n"
        "2. Or just send matches as text\n"
        "3. Wait a few seconds for analysis\n\n"
        "*Example Format:*\n"
        "`Arsenal vs Chelsea - Home Win @1.85`\n"
        "`Man City vs Liverpool - Over 2.5 @1.75`\n\n"
        f"📊 Free tries remaining: {remaining}/{MAX_FREE_TRIES}"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /vip — prompt upgrade to VIP."""
    if not await _ensure_private(update):
        return
    await update.message.reply_text(
        _vip_upgrade_message(),
        parse_mode="Markdown"
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze — analyze a betting slip from text."""
    if not await _ensure_private(update):
        return

    user = update.effective_user
    _track_user(user_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name, action="/analyze")

    if not _check_free_limit(user.id):
        await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        return

    raw_text = " ".join(context.args) if context.args else ""

    if not raw_text:
        await update.message.reply_text(
            "\U0001f4cb *Slip Analyzer*\n\n"
            "Paste your betting slip and I'll analyze it:\n\n"
            "*Usage:* `/analyze your slip here`\n\n"
            "*Example:*\n"
            "`Arsenal vs Chelsea - Home Win @1.85`\n"
            "`Man City vs Liverpool - Over 2.5 @1.75`",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_analyze"] = True
        return

    context.user_data["awaiting_analyze"] = True
    progress = await update.message.reply_text("\u23f3 Analyzing matches with Professional AI Engine...")
    
    try:
        result = await asyncio.to_thread(analyze_slip_with_search, raw_text)
        await progress.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
        _track_slip_analyzed(user.id, details=raw_text[:500])
        
        # Check if limit reached after this analysis
        remaining = MAX_FREE_TRIES - _get_slip_count(user.id)
        if remaining <= 0:
            await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        elif remaining <= 2:
            await update.message.reply_text(f"⚠️ You have {remaining} free {'try' if remaining == 1 else 'tries'} left. Upgrade to VIP for unlimited analysis: {VIP_BOT_USERNAME}")
        
    except Exception as e:
        logger.error(f"Error analyzing text input: {e}", exc_info=True)
        await progress.edit_text(f"\u274c Analysis failed: {str(e)}")


async def handle_analyze_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages — check for slip patterns or /analyze flow."""
    text = update.message.text or ""
    user = update.effective_user
    _track_user(user_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name, action="text_message")
    logger.info(f"Received text message: {text[:100]}")

    vs_count = len(re.findall(r'\bvs?\.?\b', text, re.IGNORECASE))
    logger.info(f"vs_count={vs_count}, len(text)={len(text)}")

    if vs_count >= 1 and len(text) > 10:
        context.user_data["awaiting_analyze"] = True
        logger.info("Set awaiting_analyze=True")

    if not context.user_data.get("awaiting_analyze"):
        logger.info("awaiting_analyze is False, ignoring message")
        return

    context.user_data["awaiting_analyze"] = False
    raw_text = update.message.text or ""

    if not raw_text.strip():
        await update.message.reply_text("\u274c No text detected. Try again with /analyze")
        return

    # Check free limit
    if not _check_free_limit(user.id):
        await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        return

    logger.info(f"Processing analysis for: {raw_text[:100]}")
    progress = await update.message.reply_text("\u23f3 Analyzing matches with Professional AI Engine...")
    
    try:
        result = await asyncio.to_thread(analyze_slip_with_search, raw_text)
        await progress.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
        _track_slip_analyzed(user.id, details=raw_text[:500])
        
        # Check if limit reached after this analysis
        remaining = MAX_FREE_TRIES - _get_slip_count(user.id)
        if remaining <= 0:
            await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        elif remaining <= 2:
            await update.message.reply_text(f"⚠️ You have {remaining} free {'try' if remaining == 1 else 'tries'} left. Upgrade to VIP for unlimited analysis: {VIP_BOT_USERNAME}")
        
    except Exception as e:
        logger.error(f"Error analyzing text input: {e}", exc_info=True)
        await progress.edit_text(f"\u274c Analysis failed: {str(e)}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads — extract text with OCR and analyze."""
    if not await _ensure_private(update):
        return

    user = update.effective_user
    _track_user(user_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name, action="photo_upload")

    # Check free limit
    if not _check_free_limit(user.id):
        await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        return

    progress = await update.message.reply_text("📷 Processing image...")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        extracted_text = extract_text_from_image(tmp_path)
        
        import os
        os.unlink(tmp_path)

        if not extracted_text or len(extracted_text.strip()) < 10:
            await progress.edit_text("❌ Could not read text from image. Please send a clearer photo or paste the text directly.")
            return

        logger.info(f"OCR extracted: {extracted_text[:100]}")
        await progress.edit_text("🔍 Analyzing slip with Professional AI Engine...")

        result = await asyncio.to_thread(analyze_slip_with_search, extracted_text)
        await progress.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
        _track_slip_analyzed(user.id, details=extracted_text[:500])

        # Check if limit reached after this analysis
        remaining = MAX_FREE_TRIES - _get_slip_count(user.id)
        if remaining <= 0:
            await update.message.reply_text(_vip_upgrade_message(), parse_mode="Markdown")
        elif remaining <= 2:
            await update.message.reply_text(f"⚠️ You have {remaining} free {'try' if remaining == 1 else 'tries'} left. Upgrade to VIP for unlimited analysis: {VIP_BOT_USERNAME}")

    except Exception as e:
        logger.error(f"Error processing photo: {e}", exc_info=True)
        await progress.edit_text(f"❌ Analysis failed: {str(e)}")


def extract_text_from_image(image_path: str) -> str:
    """Extract text from image using Tesseract OCR."""
    import pytesseract
    from PIL import Image

    tesseract_path = os.environ.get("TESSERACT_CMD")
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    try:
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, config='--psm 4')
        return text.strip()
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return ""


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search — use DuckDuckGo search-based slip analysis."""
    if not await _ensure_private(update):
        return

    await update.message.reply_text(
        "\U0001f50d *Search-Based Analysis*\n\n"
        "Send me your betting slip as text.\n"
        "I'll search for real form data for each match!\n\n"
        "Example:\n"
        "`Arsenal vs Chelsea @1.85`\n"
        "`Man City vs Liverpool @2.10`",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_analyze"] = True


async def cmd_full(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /full — show detailed analysis (placeholder)."""
    if not await _ensure_private(update):
        return

    await update.message.reply_text(
        "\u2139\ufe0f *Full Analysis*\n\n"
        "Detailed analysis is available after a slip analysis.\n"
        "Send your slip first, then use /full to see more details.",
        parse_mode="Markdown"
    )


# =============================================================================
# ERROR HANDLER
# =============================================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled exceptions."""
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update):
        msg = update.effective_message
        if msg:
            await msg.reply_text("Something went wrong. Please try again later.")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Initialize and start the free bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("vip", cmd_vip))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("full", cmd_full))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_analyze_text))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    app.add_error_handler(error_handler)

    logger.info("SportyBot Free is starting...")
    print("SportyBot Free is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
