"""Components map, left to right:
Trigger (note dropped in Telegram) -> Input (text / transcribed voice) ->
Processing (Gemini scores it 0-10, rejects low scores) -> Context (Google
News hook via Serper) -> AI (Gemini drafts in Meera's voice skill) ->
Output (draft sent to the Review Gate - Meera edits and publishes herself)."""
from datetime import date

import config
import storage
from services import llm, search, style


def process_note(note_text):
    """Runs one note through the pipeline. Returns a dict describing what
    happened, so the Telegram layer knows what to send back."""
    note = storage.add_note(note_text)

    try:
        triage = llm.triage_note(note_text, storage.recent_topics())
    except llm.LLMError as exc:
        return {"outcome": "error", "note": note, "message": f"Triage failed: {exc}"}

    score = _as_score(triage.get("score"))
    passed = score >= config.TRIAGE_SCORE_THRESHOLD and bool(triage.get("core_claim"))
    note_fields = dict(
        status="drafted" if passed else "rejected",
        score=score,
        pillar=triage.get("pillar"),
        core_claim=triage.get("core_claim"),
        topic_tags=triage.get("topic_tags") or [],
        reason=triage.get("reason"),
        missing=triage.get("missing"),
    )
    note.update(note_fields)
    storage.update_note(note["id"], **note_fields)

    if not passed:
        return {"outcome": "rejected", "note": note, "triage": triage}

    return _draft(note, triage)


def _as_score(value):
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return 0


def _find_news_hook(note, triage):
    """Context step. Returns the curated reference, or None - a missing hook
    is never fatal, Meera would rather get a draft without one than no draft."""
    try:
        query_plan = llm.generate_search_queries(
            triage["core_claim"], triage.get("topic_tags") or [], note["text"]
        )
        raw_results = search.search_news_multi(query_plan.get("queries") or [], num_per_query=6)
        if not raw_results:
            return None
        curated = llm.curate_reference(
            triage["core_claim"],
            query_plan.get("date_window_days", 30),
            date.today().isoformat(),
            raw_results,
        )
    except llm.LLMError:
        return None
    if curated.get("available") and curated.get("selected"):
        return curated["selected"]
    return None


def _draft(note, triage):
    reference = _find_news_hook(note, triage)
    today = date.today().isoformat()

    try:
        drafted = llm.draft_post(
            triage["core_claim"],
            note["text"],
            storage.load_voice_skill(),
            storage.load_voice_examples(),
            reference,
            today,
        )
    except llm.LLMError as exc:
        return {"outcome": "error", "note": note, "message": f"Draft failed: {exc}"}

    draft_text = style.to_meera_style((drafted.get("draft") or "").strip())
    draft = storage.add_draft({
        "note_id": note["id"],
        "core_claim": triage["core_claim"],
        "draft": draft_text,
        "current_reference_used": drafted.get("current_reference_used"),
        "reference_meta": reference,
        "assumptions": _audit(note["text"], reference, today, draft_text, drafted),
        "word_count": len(draft_text.split()),
    })

    return {"outcome": "drafted", "note": note, "triage": triage, "draft": draft}


def _audit(note_text, reference, today, draft_text, drafted):
    """The drafter under-reports its own inventions, so a separate pass checks
    every claim against the note and reference. Falls back to the drafter's
    self-reported list if the audit call fails."""
    try:
        return llm.audit_claims(note_text, reference, today, draft_text).get("unsupported") or []
    except llm.LLMError:
        return drafted.get("assumptions") or []
