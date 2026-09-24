Meera's own writing, from the case seed data ("published/" - 4 LinkedIn posts
and 11 newsletters), one piece per `.txt` file.

- `meera_voice_skill.md` - the voice skill: rules distilled from all 15
  pieces. Loaded into the draft prompt as the system-level style guide.
- `linkedin_post_*.txt` - passed to the drafter verbatim as few-shot
  examples (the first `MAX_VOICE_EXAMPLES` files in sort order, which are the
  four LinkedIn posts - same format as the output).
- `newsletter_*.txt` - kept as source material for the skill; not sent on
  every draft call, to keep prompts lean.
