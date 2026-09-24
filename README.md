# Skinstinct content bot

Meera keeps dropping notes - typed or voice - into a Telegram channel. This
bot transcribes voice notes, scores each note 0-10 for publishability,
rejects the weak ones with a reason, finds a current industry news hook for
the rest, drafts a LinkedIn post in her voice, fact-checks the draft against
her note, and sends it back to the channel for her to review. It never
publishes anything on its own.

## Components map

| Actor | Step | What happens | Code |
|---|---|---|---|
| Meera (Founder) | Trigger | Drops a voice note or text note into Telegram | - |
| Telegram | Input | Receives the note; voice notes are transcribed to text (Gemini audio - the Bot API doesn't expose Telegram's own transcription) | `services/telegram.py` `note_from_message` |
| Gemini API (Triage) | Processing | Scores the note 0-10 (specificity, point of view, pillar fit, enough to build on); below 6 is rejected with what's missing | `services/llm.py` `triage_note` |
| Google News (Context) | Context | Gemini writes news queries, Serper's Google News endpoint fetches results, Gemini picks one credible, recent hook or none | `pipeline.py` `_find_news_hook` |
| Gemini API | AI | Drafts the post using Meera's voice skill + her 4 LinkedIn posts as examples; a second pass audits every claim against her note | `services/llm.py` `draft_post`, `audit_claims` |
| Review Gate (Meera) | Output | Review card (score, hook, claims to check) + the draft with a "Post on LinkedIn" button that opens the composer pre-filled; she edits and publishes | `services/telegram.py` `send_result` |

The Cut: this does not auto-publish to LinkedIn. Meera wants a draft ready to
*look at* - the review gate is the product, not a missing feature. The
button only pre-fills LinkedIn's composer; nothing is posted until she posts.

## Meera's voice

`voice_reference/` holds her 15 published pieces from the case seed data and
`meera_voice_skill.md`, the style rules distilled from them. Each draft gets
the skill as its style guide and her 4 LinkedIn posts as examples. Mechanical
rules the model ignores under pressure (British spelling, no em dashes) are
enforced in `services/style.py` instead of the prompt. The claims audit
exists because the drafter under-reports its own inventions - specifically
anything about Skinstinct she didn't say, which is the failure that ended
her content-writer experiment.

## Setup

```bash
cd skinstinct_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- **TELEGRAM_BOT_TOKEN** - from [@BotFather](https://t.me/BotFather)
- **TELEGRAM_CHAT_ID** - already set to `-1004461281816`; change if needed
- **GEMINI_API_KEY** - [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **SERPER_API_KEY** - [serper.dev](https://serper.dev) (free tier is enough)

**Add the bot as an administrator of the channel** (`-1004461281816`) - a bot
only receives channel posts if it's an admin member, even with no special
permissions checked.

Optionally drop Meera's actual published posts into `voice_reference/` as
`.txt` files (see that folder's README) - without them the bot still runs,
just with looser voice matching.

Run it locally (polling):

```bash
python main.py
```

Post a note in the channel and watch for the reply.

## Deploying to Vercel

Vercel runs serverless functions, not long-running processes, so this uses a
**webhook** ([api/webhook.py](api/webhook.py)) instead of `bot.py`'s polling
loop - Telegram pushes each channel post to the deployed URL directly.

1. **Import the repo into Vercel** (vercel.com -> New Project -> this repo).
   No build settings needed - `vercel.json` and `requirements.txt` at the
   repo root are picked up automatically.
2. **Set environment variables** in the Vercel project (Settings ->
   Environment Variables): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   `GEMINI_API_KEY`, `GEMINI_MODEL`, `SERPER_API_KEY` - same values as your
   local `.env`.
3. **Deploy**, then point Telegram at the deployed URL:

   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-project>.vercel.app/api/webhook"
   ```

4. Post a note in the channel - Telegram calls the webhook directly, no
   polling process needed.

**Known limitation on Vercel:** the filesystem is read-only outside `/tmp`,
and `/tmp` isn't guaranteed to persist between invocations. `config.py`
detects `VERCEL=1` (set automatically by Vercel) and points storage at
`/tmp` so it mostly works within a warm container, but the recent-topics
dedupe and note/draft history are **best-effort, not reliably persistent**
in this deployment - a cold start can lose them. For real persistence, swap
`storage.py` for an external store (Upstash Redis's REST API is a small,
serverless-friendly fit) rather than flat files.

To go back to polling mode (e.g. to debug locally), call `deleteWebhook`
first - Telegram only allows one delivery method at a time:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

## Project layout

```
config.py              Env vars, paths, constants
storage.py              Flat-file JSON storage for notes and drafts
services/
  llm.py                Gemini calls: transcribe, triage score, news queries,
                        hook curation, draft, claims audit
  search.py             Serper (Google News) search wrapper
  telegram.py           Telegram I/O: note intake (incl. voice) + Review Gate
  style.py              Enforces British spelling / no em dashes on drafts
pipeline.py             Orchestrates one note through the components map
bot.py                  Local dev entrypoint: long-polling handler
main.py                 Local dev entrypoint
api/webhook.py          Vercel entrypoint: webhook handler (Flask/WSGI)
vercel.json             Vercel function config (maxDuration)
pyproject.toml          Vercel Python build: deps + entrypoint
voice_reference/        Meera's 15 published pieces + meera_voice_skill.md
data/                   notes.json, drafts.json (created on first run, local only)
```

## Known simplifications

- **Storage is flat JSON files**, not a database - single founder, a few
  notes a week, no concurrent writers to worry about.
- **No transcription step** - notes are expected as text by the time they
  hit the channel (Telegram's built-in voice-to-text, or Meera typing them
  herself), matching how she already works.
- **No retry/backoff on the news search or Gemini calls** - a failed search
  just means the draft goes out without a current reference; a failed draft
  call surfaces as an error reply rather than a silent drop.
