Drop Meera's own writing here as plain `.txt` files (one piece per file) -
her 4 LinkedIn posts and however many of the 11 newsletters read as close to
LinkedIn voice. These are used as few-shot voice examples in the draft step,
verbatim - not summarized, not paraphrased.

If this folder is empty, the bot still works: it falls back to the voice
rules written into the draft prompt, but matching will be looser without her
actual sentences to imitate.

Up to 4 examples are used per draft (see `MAX_VOICE_EXAMPLES` in `config.py`).
