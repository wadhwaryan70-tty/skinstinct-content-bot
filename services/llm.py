"""The AI steps of the pipeline: transcribe a voice note, score it for
publishability, generate search queries, curate the best news hook, then
draft the post in Meera's voice."""
import base64
import json
import re

import requests

import config

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


def _generate(system, parts, max_tokens, temperature, json_mode):
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set.")

    generation_config = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
        # gemini-3.6-flash thinks by default, and thinking tokens count against
        # maxOutputTokens - left on, it truncates the JSON before it closes.
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }
    try:
        resp = requests.post(
            _GEMINI_URL.format(model=config.GEMINI_MODEL),
            params={"key": config.GEMINI_API_KEY},
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise LLMError(f"Gemini API request failed: {exc}") from exc

    try:
        raw_text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError):
        raw_text = ""
    if not raw_text:
        raise LLMError(f"Gemini returned an empty response: {data}")
    return raw_text


def _call_json(system, user_content, max_tokens=1200, temperature=0.3):
    raw_text = _generate(system, [{"text": user_content}], max_tokens, temperature, json_mode=True)
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


TRANSCRIBE_SYSTEM = """Transcribe this voice note verbatim. It is a skincare founder talking to \
herself - expect ingredient names (niacinamide, ascorbic acid, ceramide NP, bakuchiol...), pH \
values, percentages, and Indian place names; spell them correctly. Drop filler sounds (um, uh) \
but keep every substantive word. Output only the transcript, no preamble."""


def transcribe_audio(audio_bytes, mime_type):
    parts = [
        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode()}},
        {"text": "Transcribe this voice note."},
    ]
    return _generate(TRANSCRIBE_SYSTEM, parts, max_tokens=2000, temperature=0.0, json_mode=False)


TRIAGE_SYSTEM = """You score raw content notes for Meera Pillai, founder of Skinstinct (D2C \
skincare, minimal-ingredient formulations, Mumbai). She has a pharma formulation background and \
writes long, precise LinkedIn posts about formulation science, ingredient deep-dives, industry \
transparency, India-specific skincare context, and her founder story. Her audience is 28-40 year \
old urban women who are tired of being sold to.

You get ONE raw note (a voice-note transcript or a quick typed thought). Score how publishable it \
is as the seed of a 400-550 word LinkedIn post in her voice, from 0 to 10.

Score = sum of:
- Specificity (0-3): a number, a mechanism, a named ingredient or pH, a concrete manufacturing \
detail, a real customer DM or return pattern. 0 if it's all feeling, no substance.
- Point of view (0-3): a claim she'd defend, a misconception it corrects, a gap between what \
labels say and what the chemistry does.
- Fit (0-2): sits in one of her pillars - Ingredient Deep-Dive, Formulation Science, \
India-Specific Context, Industry Transparency, Founder Story, Consumer Education, Brand Philosophy.
- Enough to build on (0-2): could carry ~500 words without inventing facts she didn't give.

Caps:
- Same theme as a recent post (list given) -> max 3.
- Pure mood, logistics, or a to-do ("call the CM tomorrow") -> max 2.
- Only a product plug with no idea behind it -> max 3.

OUTPUT (JSON only):
{
  "score": <int 0-10>,
  "pillar": "<one of the pillars above, or null>",
  "reason": "<one sentence, specific to this note - why this score>",
  "core_claim": "<the one-sentence version of the idea she's making, or null if there isn't one>",
  "missing": "<if score is low: what she'd need to add to make it publishable, else null>",
  "topic_tags": ["<short tags, e.g. niacinamide, ph, humidity, returns>"]
}"""


def triage_note(note_text, recent_topic_tags):
    user_content = (
        f"Recent post topics (last {config.RECENT_TOPICS_WINDOW_DAYS} days): "
        f"{', '.join(recent_topic_tags) or 'none'}\n"
        f"Note:\n\"\"\"\n{note_text}\n\"\"\""
    )
    return _call_json(TRIAGE_SYSTEM, user_content, max_tokens=600, temperature=0.1)


QUERY_SYSTEM = """You generate search queries to find a current news item or industry data point \
that could ground a LinkedIn post for a skincare founder. The post's core claim is given below. \
You are not writing the post - only generating queries to feed into a news search tool.

Generate 2-3 short queries that would surface:
- Recent industry news (regulatory changes in India or globally, ingredient bans/approvals, \
labelling rules, market reports)
- Recent dermatology/cosmetic science research or studies
- Category-level news (D2C skincare in India, clean beauty, "actives" trend coverage)

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
        f"Original note (for extra context): \"\"\"{note_text}\"\"\""
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


DRAFT_SYSTEM_TEMPLATE = """You are ghostwriting a LinkedIn post as Meera Pillai, founder of \
Skinstinct. Write as her, in first person - the reader should not be able to tell it wasn't her.

Follow this voice skill exactly. It was derived from everything she has published:

{voice_skill}

TASK
- Develop the core idea from her note into ONE LinkedIn post of 400-550 words, 6-9 paragraphs, \
paragraphs separated by a blank line.
- Imitate the rhythm of her example posts (supplied by the user), not their topics, and not \
their sentences - don't reuse her lines verbatim. The one exception is her recurring close \
("...that is also useful information"), which is fine to echo.

GROUNDING - she will stop using this tool the first time it puts words in her mouth:
- Anything about Skinstinct - what it sells or doesn't sell, what it has tested, what it is \
changing, plans, timelines, internal results, numbers - may ONLY come from her note. If the note \
doesn't say it, don't write it. No invented commitments ("we are now testing at..."), no \
"we don't currently sell X" unless the note says so.
- No invented dates or times ("last month", "in April") unless the note or reference gives them.
- General chemistry/industry mechanism is fine to explain, but keep numbers she didn't give out \
of it, or hedge them the way she does ("typically around...").
- If a current reference is given, use it the way she would - as one attributed piece of \
evidence, not the headline. Describe its timing accurately from its publication date relative \
to today (a report from five months ago is not "this month").

OUTPUT (JSON only):
{{
  "draft": "<the full post text>",
  "current_reference_used": "<one line on what you referenced and where, or null>",
  "assumptions": ["<each claim you supplied that wasn't in her note or the reference>"],
  "word_count": <int>
}}"""


def _reference_block(reference, today_date):
    if not reference:
        return "(none - do not reference anything current or recent)"
    return (
        f"{reference.get('usable_snippet')}\n"
        f"Source: {reference.get('source')} - \"{reference.get('headline')}\"\n"
        f"Published: {reference.get('date')} (today is {today_date})"
    )


def draft_post(core_claim, note_text, voice_skill, published_examples, reference, today_date):
    examples_block = "\n\n=====\n\n".join(published_examples) if published_examples else "(none on file)"
    user_content = (
        f"HER PUBLISHED LINKEDIN POSTS (voice reference - match style, not topic):\n\n"
        f"{examples_block}\n\n=====\n\n"
        f"HER NOTE:\n\"\"\"{note_text}\"\"\"\n\n"
        f"CORE IDEA TO DEVELOP: {core_claim}\n\n"
        f"CURRENT REFERENCE:\n{_reference_block(reference, today_date)}"
    )
    system = DRAFT_SYSTEM_TEMPLATE.format(voice_skill=voice_skill or "(voice skill missing)")
    return _call_json(system, user_content, max_tokens=3000, temperature=0.7)


AUDIT_SYSTEM = """You fact-check a ghostwritten LinkedIn draft before the founder, Meera Pillai \
of Skinstinct, reviews it. Her only sources are HER NOTE and the CURRENT REFERENCE. List every \
claim in the draft that neither source supports, so she can verify or cut it before posting.

Flag:
- Anything about Skinstinct not stated in her note: products sold or not sold, tests run, \
results, changes, plans, commitments, timelines. These matter most - prefix them "SKINSTINCT: ".
- Specific numbers, dates, time references ("last month"), places, or study results not in \
either source.
- Anything attributed to the reference that the reference doesn't say, or a wrong description \
of when it was published.

Don't flag: her own opinions restated, general framing, or well-established textbook chemistry \
stated without specific numbers.

Quote or closely paraphrase the draft's wording in each item so she can find it. Most important \
first. Empty list if everything is supported.

OUTPUT (JSON only):
{"unsupported": ["<claim> - <why it needs checking>"]}"""


def audit_claims(note_text, reference, today_date, draft_text):
    user_content = (
        f"HER NOTE:\n\"\"\"{note_text}\"\"\"\n\n"
        f"CURRENT REFERENCE:\n{_reference_block(reference, today_date)}\n\n"
        f"DRAFT:\n\"\"\"{draft_text}\"\"\""
    )
    return _call_json(AUDIT_SYSTEM, user_content, max_tokens=1200, temperature=0.0)
