"""Trigger (Telegram message) -> Input (note) -> Context (voice + news) ->
Processing/AI (triage, search, curate, draft) -> Output (draft back to Meera)."""
from datetime import date

import storage
from services import llm, search


def process_note(note_text):
    """Runs the full pipeline for one incoming note. Returns a dict describing
    what happened, so the bot handler knows what to reply with."""
    note = storage.add_note(note_text)

    try:
        triage = llm.triage_note(note_text, storage.recent_topics())
    except llm.LLMError as exc:
        return {"outcome": "error", "note": note, "message": f"Triage failed: {exc}"}

    note_fields = dict(
        status=triage.get("verdict", "hold"),
        core_claim=triage.get("core_claim"),
        topic_tags=triage.get("topic_tags") or [],
        confidence=triage.get("confidence"),
        reason=triage.get("reason"),
    )
    note.update(note_fields)
    storage.update_note(
        note["id"],
        **note_fields,
    )

    if triage.get("verdict") != "develop":
        return {"outcome": triage.get("verdict", "hold"), "note": note, "triage": triage}

    return _develop(note, triage)


def _develop(note, triage):
    core_claim = triage["core_claim"]
    topic_tags = triage.get("topic_tags") or []

    current_snippet = None
    reference_meta = None
    try:
        query_plan = llm.generate_search_queries(core_claim, topic_tags, note["text"])
        raw_results = search.search_news_multi(
            query_plan.get("queries") or [], num_per_query=6
        )
        if raw_results:
            curated = llm.curate_reference(
                core_claim,
                query_plan.get("date_window_days", 30),
                date.today().isoformat(),
                raw_results,
            )
            if curated.get("available") and curated.get("selected"):
                reference_meta = curated["selected"]
                current_snippet = reference_meta.get("usable_snippet")
    except llm.LLMError:
        # A missing news hook is not fatal - Meera would rather get a draft
        # without one than no draft at all.
        pass

    voice_examples = storage.load_voice_examples()

    try:
        drafted = llm.draft_post(core_claim, note["text"], voice_examples, current_snippet)
    except llm.LLMError as exc:
        return {"outcome": "error", "note": note, "message": f"Draft failed: {exc}"}

    draft = storage.add_draft({
        "note_id": note["id"],
        "core_claim": core_claim,
        "draft": drafted.get("draft", ""),
        "current_reference_used": drafted.get("current_reference_used"),
        "reference_meta": reference_meta,
        "assumptions": drafted.get("assumptions") or [],
        "word_count": drafted.get("word_count"),
    })

    return {"outcome": "develop", "note": note, "triage": triage, "draft": draft}
