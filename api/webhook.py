"""Vercel entrypoint: Telegram calls this over HTTP for every channel post,
instead of the bot long-polling for updates (see bot.py for the local
equivalent). Vercel's Python runtime looks for a top-level `app` (WSGI) in
this file."""
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from flask import Flask, jsonify, request

import config
import pipeline
from reply_format import format_reply

app = Flask(__name__)

# Telegram retries a webhook delivery if it doesn't get a response quickly
# enough, which this pipeline's multi-call AI chain can genuinely exceed -
# without this, a slow-but-successful run gets silently reprocessed and
# double-posts. This only catches retries that land on the same warm
# container (the common case for near-immediate retries); a cold start
# still resets it, since there's no shared store across invocations here.
_MAX_SEEN = 200
_seen_update_ids = set()
_seen_update_order = deque()


def _already_seen(update_id):
    if update_id is None:
        return False
    if update_id in _seen_update_ids:
        return True
    if len(_seen_update_order) >= _MAX_SEEN:
        oldest = _seen_update_order.popleft()
        _seen_update_ids.discard(oldest)
    _seen_update_order.append(update_id)
    _seen_update_ids.add(update_id)
    return False


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
    if _already_seen(update.get("update_id")):
        return jsonify({"ok": True})

    message = update.get("channel_post") or update.get("message")
    if not message or "text" not in message:
        return jsonify({"ok": True})

    chat_id = str(message.get("chat", {}).get("id", ""))
    if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
        return jsonify({"ok": True})

    result = pipeline.process_note(message["text"])
    _send_message(chat_id, format_reply(result))
    return jsonify({"ok": True})
