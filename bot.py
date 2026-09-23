"""Local dev entrypoint: long-polling Telegram bot. Not used on Vercel (see
api/webhook.py) - polling is a process that runs forever, which serverless
functions can't do."""
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
import pipeline
from reply_format import format_reply

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return

    chat_id = str(update.effective_chat.id) if update.effective_chat else None
    if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
        return

    result = pipeline.process_note(message.text)
    await message.reply_text(format_reply(result))


def build_app():
    missing = config.missing_keys()
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)}. Check your .env file.")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def run():
    logging.basicConfig(level=logging.INFO)
    app = build_app()
    logger.info("Skinstinct content bot polling for notes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
