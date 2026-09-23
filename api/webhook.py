"""Vercel entrypoint: Telegram calls this over HTTP for every channel post,
instead of the bot long-polling for updates (see bot.py for the local
equivalent). Vercel's Python runtime looks for a top-level `app` (WSGI) in
this file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from flask import Flask, jsonify, request

import config
import pipeline
from reply_format import format_reply

app = Flask(__name__)


def _send_message(chat_id, text):
    if not config.TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except requests.RequestException:
        pass


@app.route("/api/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"ok": True, "message": "Skinstinct bot webhook is live."})

    update = request.get_json(force=True, silent=True) or {}
    message = update.get("channel_post") or update.get("message")
    if not message or "text" not in message:
        return jsonify({"ok": True})

    chat_id = str(message.get("chat", {}).get("id", ""))
    if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
        return jsonify({"ok": True})

    result = pipeline.process_note(message["text"])
    _send_message(chat_id, format_reply(result))
    return jsonify({"ok": True})
