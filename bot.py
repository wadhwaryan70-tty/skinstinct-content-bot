"""Telegram message handler - the Trigger and Output ends of the pipeline.
Reads notes from Meera's channel, replies with a draft (or a short status),
never posts anywhere on its own."""
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
import pipeline

logger = logging.getLogger(__name__)


def _format_draft_reply(result):
    draft = result["draft"]
    lines = [
        "\U0001F4DD Draft ready for review:",
        "",
        draft["draft"],
        "",
        f"({draft.get('word_count', '?')} words)",
    ]
    if draft.get("current_reference_used"):
        lines += ["", f"\U0001F310 Current reference: {draft['current_reference_used']}"]
        meta = draft.get("reference_meta") or {}
        if meta.get("url"):
            lines.append(f"Source: {meta['source']} ({meta['date']}) - {meta['url']}")
    if draft.get("assumptions"):
        lines += ["", "⚠️ Assumptions made (check these):"]
        lines += [f"- {a}" for a in draft["assumptions"]]
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return

    chat_id = str(update.effective_chat.id) if update.effective_chat else None
    if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
        return

    result = pipeline.process_note(message.text)
    outcome = result["outcome"]

    if outcome == "develop":
        reply = _format_draft_reply(result)
    elif outcome == "hold":
        reply = f"\U0001F4CC Noted - might be worth developing later. ({result['triage'].get('reason', '')})"
    elif outcome == "discard":
        reply = f"\U0001F5D1 Skipping this one. ({result['triage'].get('reason', '')})"
    else:
        reply = f"⚠️ {result.get('message', 'Something went wrong.')}"

    await message.reply_text(reply)


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
