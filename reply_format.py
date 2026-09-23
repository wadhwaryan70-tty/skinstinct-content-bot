"""Turns a pipeline result into the text sent back to the channel. Shared by
the local polling bot (bot.py) and the Vercel webhook handler (api/webhook.py)
so the two entrypoints can't drift."""


def format_reply(result):
    outcome = result["outcome"]

    if outcome == "develop":
        return _format_draft_reply(result)
    if outcome == "hold":
        return f"\U0001F4CC Noted - might be worth developing later. ({result['triage'].get('reason', '')})"
    if outcome == "discard":
        return f"\U0001F5D1 Skipping this one. ({result['triage'].get('reason', '')})"
    return f"⚠️ {result.get('message', 'Something went wrong.')}"


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
