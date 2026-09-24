"""Deterministic fixes for the mechanical parts of Meera's style. The model
drifts to US spelling and em dashes no matter what the prompt says, so these
are enforced in code rather than asked for."""
import re

# Words ending in -ize that aren't the -ise/-ize verb suffix.
_IZE_EXCEPTIONS = {"size", "sizes", "sized", "sizing", "resize", "resized", "resizing", "downsize",
                   "downsized", "oversize", "oversized", "undersized", "upsize", "midsize", "prize",
                   "prizes", "prized", "seize", "seizes", "seized", "seizing", "capsize", "capsized",
                   "maize", "baize"}
_IZE = re.compile(r"\b(\w+?)iz(e|es|ed|ing|ation|ations|er|ers)\b", re.IGNORECASE)

_WORDS = {
    "behavior": "behaviour", "behaviors": "behaviours", "behavioral": "behavioural",
    "color": "colour", "colors": "colours", "colored": "coloured", "colorless": "colourless",
    "flavor": "flavour", "flavors": "flavours", "odor": "odour", "odors": "odours",
    "favorite": "favourite", "center": "centre", "centers": "centres", "fiber": "fibre",
    "fibers": "fibres", "analyze": "analyse", "analyzes": "analyses", "analyzed": "analysed",
    "analyzing": "analysing", "gray": "grey", "labeling": "labelling", "labeled": "labelled",
    "modeling": "modelling",
}
_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)


def _match_case(original, replacement):
    return replacement.capitalize() if original[:1].isupper() else replacement


def _fix_ize(m):
    word = m.group(0)
    if word.lower() in _IZE_EXCEPTIONS:
        return word
    return m.group(1) + ("is" if word[len(m.group(1))].islower() else "IS") + m.group(2)


def to_meera_style(text):
    text = text.replace("—", " - ").replace("–", " - ")
    text = re.sub(r" {2,}", " ", text)
    text = _WORD.sub(lambda m: _match_case(m.group(0), _WORDS[m.group(0).lower()]), text)
    return _IZE.sub(_fix_ize, text)
