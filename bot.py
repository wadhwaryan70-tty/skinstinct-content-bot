"""Local dev entrypoint: long-polling Telegram bot. Not used on Vercel (see
api/webhook.py) - polling is a process that runs forever, which serverless
functions can't do. Run `deleteWebhook` first; Telegram allows one or the
other."""
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
import pipeline
from services import telegram as tg

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat_id = str(update.effective_chat.id) if update.effective_chat else None
    if message is None or (config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID):
        return

    note_text, source = tg.note_from_message(message.to_dict())
    if note_text:
        tg.send_result(chat_id, pipeline.process_note(note_text), source)


def build_app():
    missing = config.missing_keys()
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)}. Check your .env file.")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.VOICE | filters.AUDIO, handle_message
    ))
    return app


def run():
    logging.basicConfig(level=logging.INFO)
    app = build_app()
    logger.info("Skinstinct content bot polling for notes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
