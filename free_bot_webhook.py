"""
SportyBot Free Bot - Webhook Mode
Uses ngrok to expose local Flask server for Telegram webhook.
Avoids polling conflicts with Render.
"""

import os
import logging
import threading
import time
import asyncio
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest

from slip_analyzer.search_analyzer import analyze_slip_with_search

# ngrok auth token - get from https://dashboard.ngrok.com/get-started/your-authtoken
NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN", "")

BOT_TOKEN = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_PATH = "/webhook"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot_app = None
webhook_url = None


async def _ensure_private(update: Update) -> bool:
    if update.effective_chat and update.effective_chat.type != "private":
        await update.message.reply_text("\u274c This bot only works in private chats.")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_private(update):
        return
    user = update.effective_user
    username = user.first_name or "there"
    await update.message.reply_text(
        f"Welcome to SportyBot Free, {username}!\n\n"
        f"Send me your betting slip as text and I'll analyze it using live web search.\n\n"
        f"Example:\n"
        f"`Arsenal vs Chelsea @1.85`\n"
        f"`Man City vs Liverpool @2.10`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_private(update):
        return
    await update.message.reply_text(
        "*How to Use*\n\n"
        "Send matches as text:\n"
        "`Team A vs Team B - Pick @Odds`\n\n"
        "I'll search for live form/stats and return analysis.",
        parse_mode="Markdown",
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_private(update):
        return
    raw_text = " ".join(context.args) if context.args else ""
    if not raw_text:
        await update.message.reply_text(
            "\U0001f4cb *Slip Analyzer*\n\n"
            "Usage: `/analyze your slip here`\n\n"
            "Example:\n"
            "`Arsenal vs Chelsea @1.85`",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_analyze"] = True
        return

    context.user_data["awaiting_analyze"] = True
    progress = await update.message.reply_text("\u23f3 Analyzing...")

    try:
        result = await asyncio.to_thread(analyze_slip_with_search, raw_text)
        await progress.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        await progress.edit_text(f"\u274c Analysis failed: {str(e)}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    logger.info(f"Received text: {text[:100]}")

    vs_count = text.lower().count("vs")
    if vs_count >= 1 and len(text) > 10:
        context.user_data["awaiting_analyze"] = True

    if not context.user_data.get("awaiting_analyze"):
        return

    context.user_data["awaiting_analyze"] = False
    raw_text = update.message.text or ""

    if not raw_text.strip():
        await update.message.reply_text("\u274c No text detected. Try again with /analyze")
        return

    logger.info(f"Processing analysis for: {raw_text[:100]}")
    progress = await update.message.reply_text("\u23f3 Analyzing matches...")

    try:
        result = await asyncio.to_thread(analyze_slip_with_search, raw_text)
        await progress.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        await progress.edit_text(f"\u274c Analysis failed: {str(e)}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_private(update):
        return
    await update.message.reply_text(
        "\U0001f4f8 Photo analysis is disabled. Please send matches as text.",
        parse_mode="Markdown",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception: {context.error}", exc_info=context.error)


@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if bot_app:
        update = Update.de_json(request.get_json(), bot_app.bot)
        asyncio.get_event_loop().create_task(bot_app.process_update(update))
    return jsonify({"ok": True})


@app.route("/")
def index():
    return jsonify({"status": "ok", "webhook": webhook_url})


def start_ngrok():
    """Start ngrok tunnel and return public URL."""
    import ngrok

    if NGROK_AUTH_TOKEN:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)

    listener = ngrok.forward(PORT, authtoken_from_env=bool(NGROK_AUTH_TOKEN))
    url = listener.url()
    logger.info(f"ngrok tunnel started: {url}")
    return url


def main():
    global bot_app, webhook_url

    logger.info("Starting SportyBot Free in webhook mode...")

    # Start ngrok
    webhook_url = start_ngrok()
    full_webhook = f"{webhook_url}{WEBHOOK_PATH}"
    logger.info(f"Webhook URL: {full_webhook}")

    # Create bot application
    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", cmd_start))
    bot_app.add_handler(CommandHandler("help", cmd_help))
    bot_app.add_handler(CommandHandler("analyze", cmd_analyze))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    bot_app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    bot_app.add_error_handler(error_handler)

    # Start bot with webhook
    async def setup():
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.bot.set_webhook(url=full_webhook, drop_pending_updates=True)
        logger.info(f"Webhook set to {full_webhook}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())

    logger.info("Bot started. Press Ctrl+C to stop.")

    # Start Flask server
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)


if __name__ == "__main__":
    main()
