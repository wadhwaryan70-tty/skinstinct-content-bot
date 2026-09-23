"""The AI step of the pipeline: triage a raw note, generate search queries,
curate the best current reference, then draft the post."""
import json
import re

import requests

import config

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


def _call_json(system, user_content, max_tokens=1200):
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set.")

    url = _GEMINI_URL.format(model=config.GEMINI_MODEL)
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        resp = requests.post(
            url,
            params={"key": config.GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise LLMError(f"Gemini API request failed: {exc}") from exc

    try:
        parts = data["candidates"][0]["content"]["parts"]
        raw_text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        raw_text = ""
    if not raw_text:
        raise LLMError(f"Gemini returned an empty response: {data}")

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        candidate = match.group(0) if match else cleaned
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            raise LLMError(f"Gemini returned unparseable output: {raw_text[:300]}")


TRIAGE_SYSTEM = """You are triaging raw content fragments for Meera Pillai, founder of Skinstinct \
(D2C skincare, minimal-ingredient formulations). Meera has a pharma background - she talks in \
actives, concentrations, pH, and clinical trial data, never vague wellness language. Her audience \
is 28-40 year old urban women who are skeptical of being sold to.

You will be given ONE raw fragment (a voice-note transcript or a short written note). Decide \
whether it has enough substance to become a LinkedIn post.

A fragment is WORTH DEVELOPING if it has at least one of:
- A specific claim, number, or mechanism (an ingredient %, a pH value, a manufacturing detail, a \
customer behavior pattern)
- A clear point of view or contrarian take (e.g. "the % on the label doesn't matter")
- A concrete anecdote from the manufacturing unit or a customer DM

A fragment is NOT worth developing if it is:
- A mood/feeling with no specific claim ("today was exhausting")
- A fragment of a fragment (too short/vague to reconstruct intent)
- A duplicate of a theme already drafted in the last 14 days (a list of recent topics is given - \
check against it)

OUTPUT (JSON only):
{
  "verdict": "develop" | "hold" | "discard",
  "confidence": 0-1,
  "reason": "<one sentence, specific to this fragment>",
  "core_claim": "<the one sentence version of the idea, if develop, else null>",
  "topic_tags": ["<e.g. formulation, pricing, manufacturing, customer-behavior>"]
}"""


def triage_note(note_text, recent_topic_tags):
    user_content = (
        f"Recent post topics (last 14 days): {', '.join(recent_topic_tags) or 'none'}\n"
        f"Fragment:\n\"\"\"\n{note_text}\n\"\"\""
    )
    return _call_json(TRIAGE_SYSTEM, user_content, max_tokens=500)


QUERY_SYSTEM = """You generate search queries to find a current news item or industry data point \
that could ground a LinkedIn post for a skincare founder. The post's core claim is given below. \
You are not writing the post - only generating queries to feed into a search tool.

Generate 2-3 short queries that would surface:
- Recent industry news (regulatory changes, ingredient bans/approvals, market reports)
- Recent dermatology/cosmetic science research or studies
- Competitor or category-level news (D2C skincare, clean beauty, "actives" trend coverage)

Prefer queries that connect to the SPECIFIC mechanism/claim in the note, not generic "skincare news."

OUTPUT (JSON only):
{
  "queries": ["<query 1>", "<query 2>", "<query 3>"],
  "date_window_days": <int, how recent results need to be to feel "current" for this topic>
}"""


def generate_search_queries(core_claim, topic_tags, note_text):
    user_content = (
        f"Core claim: {core_claim}\n"
        f"Topic tags: {', '.join(topic_tags)}\n"
        f"Original fragment (for extra context): \"\"\"{note_text}\"\"\""
    )
    return _call_json(QUERY_SYSTEM, user_content, max_tokens=400)


CURATION_SYSTEM = """You are selecting ONE search result to use as a "current reference" in a \
LinkedIn post for Meera Pillai (Skinstinct, minimal-ingredient skincare, pharma-trained founder, \
audience of skeptical 28-40 year old women).

You will be given a core claim and a list of raw search results. Pick the single best result to \
reference, or none if nothing qualifies.

A result QUALIFIES if it:
- Is within the date window given (reject anything older, even if topically perfect)
- Comes from a credible source (industry publication, regulatory body, peer-reviewed research, \
established news outlet - not a random blog or another brand's marketing page)
- Genuinely connects to the core claim as evidence, contrast, or context - not just a keyword match

Reject everything if the best available result is only a keyword match, or if all results are \
stale, low-credibility, or thin. Do not force a connection that isn't there. A post with no \
current reference is better than one with a forced, irrelevant one.

OUTPUT (JSON only):
{
  "available": true | false,
  "selected": {
    "headline": "<title>",
    "source": "<publication>",
    "date": "<YYYY-MM-DD>",
    "url": "<url>",
    "relevance_note": "<one sentence: how this connects to the core claim>",
    "usable_snippet": "<1-2 sentence factual summary to hand to the draft step - no editorializing>"
  } | null,
  "rejected_reason": "<if available is false, why nothing qualified, else null>"
}"""


def curate_reference(core_claim, date_window_days, today_date, search_results):
    listing = "\n".join(
        f"- [{r['query']}] \"{r['headline']}\" - {r['source']} ({r['date']}) - {r['snippet']} ({r['url']})"
        for r in search_results
    ) or "(no results returned)"
    user_content = (
        f"Core claim: {core_claim}\n"
        f"Date window: {date_window_days} days (today: {today_date})\n"
        f"Raw search results:\n{listing}"
    )
    return _call_json(CURATION_SYSTEM, user_content, max_tokens=500)


DRAFT_SYSTEM = """You write LinkedIn post drafts for Meera Pillai in her voice - not as an AI, as \
her. You are given the core idea to develop, examples of her actual published writing (voice \
reference - match sentence rhythm, vocabulary, and how she opens/closes posts, don't imitate \
topics), and possibly a current external reference to ground the post in the present.

VOICE RULES (derived from her published work):
- No wellness-industry filler ("glow up," "skin journey," "self-care"). Ever.
- Leads with a specific, checkable claim - a number, a mechanism, a contradiction - not a hook \
question.
- Cites the "why" behind the claim (chemistry, clinical data, manufacturing reality), the way a \
pharma-trained founder would, not a marketer.
- Short paragraphs, plain declarative sentences. No hashtag stuffing, no emoji rows.
- Ends by connecting the specific claim back to a customer-relevant decision (what to look for, \
what to ignore) - not a call-to-action for engagement's sake.

TASK: Write ONE LinkedIn post (180-280 words) developing the core idea below. If a current \
reference is given, weave it in naturally - as evidence or contrast, not tacked on. Do not invent \
data, clinical claims, or statistics that weren't given to you; if the note lacks a specific \
number, keep the claim qualitative rather than fabricating precision. This is a DRAFT for Meera \
to review and edit - flag anywhere you had to infer or extrapolate rather than being given the \
fact directly, in a separate "assumptions" field.

OUTPUT (JSON only):
{
  "draft": "<the full post text>",
  "current_reference_used": "<one line on what you referenced and why it fit, or null>",
  "assumptions": ["<anything you inferred rather than were told>"],
  "word_count": <int>
}"""


def draft_post(core_claim, note_text, published_examples, current_snippet):
    voice_block = "\n\n---\n\n".join(published_examples) if published_examples else (
        "(no voice samples on file yet - follow the voice rules above as closely as possible)"
    )
    reference_block = current_snippet or "(none available - do not reference anything current)"
    user_content = (
        f"Core idea to develop: {core_claim}\n"
        f"Original fragment: \"\"\"{note_text}\"\"\"\n\n"
        f"Voice reference (her own writing - match style, not topic):\n{voice_block}\n\n"
        f"Current reference to ground this in:\n{reference_block}"
    )
    return _call_json(DRAFT_SYSTEM, user_content, max_tokens=1200)
