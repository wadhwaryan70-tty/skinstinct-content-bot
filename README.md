# Skinstinct content bot

Meera keeps dropping notes into a Telegram channel. This bot reads each note,
decides if it's worth developing, finds a current news/data point to ground
it in, drafts a LinkedIn post in her voice, and replies in the same channel
with the draft for her to review. It never posts anywhere on its own.

## Components map

```
Trigger     Telegram message posted in Meera's channel
Input       The raw note text
Context     Recent post topics (dedupe) + her published voice samples +
            live news search results
Processing  Query generation, news search (Serper), result curation
AI          Gemini: triage -> generate search queries -> curate reference
            -> draft the post
Output      A reply in the same Telegram channel: either the draft (with
            assumptions + source flagged), or a short "noted"/"skipping" ack
```

The Cut: this does not auto-publish to LinkedIn. Meera wants a draft ready to
*look at* - a human approval step is not optional here, so posting stays
manual by design, not a missing feature.

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
  llm.py                The three Gemini prompts: triage, query generation +
                        reference curation, draft
  search.py             Serper news search wrapper
pipeline.py             Orchestrates trigger -> ... -> output for one note
reply_format.py         Turns a pipeline result into the reply text (shared)
bot.py                  Local dev entrypoint: long-polling handler
main.py                 Local dev entrypoint
api/webhook.py          Vercel entrypoint: webhook handler (Flask/WSGI)
vercel.json             Vercel function config (maxDuration)
voice_reference/        Meera's own writing, used as few-shot voice examples
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
