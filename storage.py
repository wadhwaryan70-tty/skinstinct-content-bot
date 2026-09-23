"""Flat-file JSON storage. A single founder, a handful of notes a week -
a real database would be an abstraction with no job to do yet."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import config


def _load(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path, items):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- notes ---

def load_notes():
    return _load(config.NOTES_FILE)


def add_note(text):
    notes = load_notes()
    note = {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "timestamp": _now_iso(),
        "status": "pending",  # pending | develop | hold | discard
        "core_claim": None,
        "topic_tags": [],
        "confidence": None,
        "reason": None,
    }
    notes.append(note)
    _save(config.NOTES_FILE, notes)
    return note


def update_note(note_id, **fields):
    notes = load_notes()
    for note in notes:
        if note["id"] == note_id:
            note.update(fields)
            break
    _save(config.NOTES_FILE, notes)


def recent_topics(window_days=None):
    """Topic tags from notes marked 'develop' in the last N days, for the
    triage step's dedupe check."""
    window_days = window_days or config.RECENT_TOPICS_WINDOW_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    tags = []
    for note in load_notes():
        if note.get("status") != "develop":
            continue
        try:
            ts = datetime.fromisoformat(note["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            tags.extend(note.get("topic_tags") or [])
    return sorted(set(tags))


# --- drafts ---

def load_drafts():
    return _load(config.DRAFTS_FILE)


def add_draft(draft):
    drafts = load_drafts()
    draft = {**draft, "id": uuid.uuid4().hex[:12], "created_at": _now_iso()}
    drafts.append(draft)
    _save(config.DRAFTS_FILE, drafts)
    return draft


# --- voice reference ---

def load_voice_examples(max_n=None):
    max_n = max_n or config.MAX_VOICE_EXAMPLES
    if not config.VOICE_REFERENCE_DIR.exists():
        return []
    examples = []
    for path in sorted(config.VOICE_REFERENCE_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            examples.append(text)
    return examples[:max_n]
