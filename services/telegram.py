"""Telegram I/O shared by both entrypoints (api/webhook.py on Vercel, bot.py
locally): turning an incoming message into note text, and sending the
Review Gate messages back. Plain Bot API calls over HTTP - no framework."""
from urllib.parse import quote

import requests

import config
from services import llm

_API = "https://api.telegram.org/bot{token}/{method}"
_FILE = "https://api.telegram.org/file/bot{token}/{path}"
_MAX_MESSAGE_CHARS = 4096
_LINKEDIN_SHARE = "https://www.linkedin.com/feed/?shareActive=true"


class TelegramError(Exception):
    pass


def _call(method, **payload):
    resp = requests.post(
        _API.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=payload, timeout=20
    )
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {data.get('description')}")
    return data["result"]


# --- input ---

def note_from_message(message):
    """Returns (note_text, source) for a Telegram message dict, or (None, None)
    if there's nothing to process. Voice notes are transcribed by Gemini -
    the Bot API doesn't expose Telegram's own transcription to bots."""
    text = (message.get("text") or message.get("caption") or "").strip()
    if text:
        return text, "text"

    audio = message.get("voice") or message.get("audio")
    if not audio:
        return None, None

    file_path = _call("getFile", file_id=audio["file_id"])["file_path"]
    resp = requests.get(_FILE.format(token=config.TELEGRAM_BOT_TOKEN, path=file_path), timeout=30)
    resp.raise_for_status()
    mime_type = _gemini_audio_mime(audio.get("mime_type"), file_path)
    return llm.transcribe_audio(resp.content, mime_type).strip(), "voice"


def _gemini_audio_mime(telegram_mime, file_path):
    # Telegram reports m4a as audio/x-m4a, which Gemini doesn't recognise.
    if telegram_mime in (None, "audio/x-m4a") and file_path.endswith((".m4a", ".mp4")):
        return "audio/mp4"
    return telegram_mime or "audio/ogg"


# --- output: the Review Gate ---

def send_result(chat_id, result, source="text"):
    outcome = result["outcome"]
    if outcome == "drafted":
        _send_review(chat_id, result, source)
    elif outcome == "rejected":
        _send(chat_id, _rejection_text(result, source))
    else:
        _send(chat_id, f"Something went wrong: {result.get('message', 'unknown error')}")


def _send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text[:_MAX_MESSAGE_CHARS], "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", **payload)


def _heard_line(result, source):
    if source != "voice":
        return []
    transcript = result["note"]["text"]
    preview = transcript if len(transcript) <= 300 else transcript[:300] + "..."
    return [f"Heard: \"{preview}\"", ""]


def _rejection_text(result, source):
    triage = result["triage"]
    lines = _heard_line(result, source) + [
        f"NOT DRAFTED - scored {result['note']['score']}/10 "
        f"(needs {config.TRIAGE_SCORE_THRESHOLD}+)",
        triage.get("reason") or "",
    ]
    if triage.get("missing"):
        lines += ["", f"To make it publishable: {triage['missing']}"]
    return "\n".join(lines).strip()


def _review_card_text(result, source):
    note, draft = result["note"], result["draft"]
    lines = _heard_line(result, source) + [
        f"NEW DRAFT FOR REVIEW - scored {note['score']}/10"
        + (f" - {note['pillar']}" if note.get("pillar") else ""),
        f"Why: {note.get('reason') or '-'}",
        "",
    ]
    ref = draft.get("reference_meta")
    if ref:
        lines.append(f"News hook: {ref.get('headline')} - {ref.get('source')} ({ref.get('date')})")
        if ref.get("url"):
            lines.append(ref["url"])
    else:
        lines.append("News hook: none good enough - draft stands on its own.")
    if draft.get("assumptions"):
        lines += ["", "Check before posting (not from your note):"]
        lines += [f"- {a}" for a in draft["assumptions"]]
    lines += [
        "",
        f"Draft below ({draft['word_count']} words). Edit anything, then tap "
        "\"Post on LinkedIn\" - it opens the composer with the text filled in. "
        "Nothing is published until you post it.",
    ]
    return "\n".join(lines)


def linkedin_share_url(post_text):
    return f"{_LINKEDIN_SHARE}&text={quote(post_text)}"


def _send_review(chat_id, result, source):
    _send(chat_id, _review_card_text(result, source))
    draft_text = result["draft"]["draft"]
    try:
        _send(chat_id, draft_text, _linkedin_button(linkedin_share_url(draft_text)))
    except TelegramError:
        # Very long drafts can exceed what Telegram accepts in a button URL;
        # fall back to an empty composer - the draft is right there to copy.
        _send(chat_id, draft_text, _linkedin_button(_LINKEDIN_SHARE))


def _linkedin_button(url):
    return {"inline_keyboard": [[{"text": "Post on LinkedIn", "url": url}]]}
