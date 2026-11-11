"""Excerpts of a text cut to a length without breaking a word.

Used for the KB excerpts in the agents' prompt, for the posts shown to the agents and to the report writer,
and for the post previews of the round events. An excerpt that ends mid-word is quoted mid-word: the report
writer quoted "vorrei dat[...]" from a post cut at 200 characters.
"""
from __future__ import annotations

import re

# Marks an excerpt cut in the middle of a sentence
ELLIPSIS = "…"
# Cut at the end of a sentence only if at least this share of the limit is kept: an end of sentence too early
# throws away useful text (on a test brief, without this threshold, 2 facts out of 20 were left out of the prompt)
MIN_SENTENCE_KEEP = 0.75
# End of sentence: . ! ? or …, with closing quotes or brackets, followed by a space.
# The space after excludes decimals and addresses (3.5, www.example.com)
SENTENCE_END = re.compile(r"[.!?…][\"'»”’)\]]*(?=\s)")


def trim_excerpt(text: str, cap: int) -> str:
    """Shortens text to at most cap characters, never cutting a word.

    Cuts after the last end of sentence that fits, if it keeps at least MIN_SENTENCE_KEEP of the limit;
    otherwise after the last whole word, and adds ELLIPSIS. Returns "" if not even one word fits.
    """
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    # endpos cap + 1: the lookahead sees the character right after the limit
    ends = [m.end() for m in SENTENCE_END.finditer(text, 0, cap + 1) if m.end() <= cap]
    if ends and ends[-1] >= MIN_SENTENCE_KEEP * cap:
        return text[: ends[-1]]
    room = cap - len(ELLIPSIS)
    if room <= 0:
        return ""
    # The last space within room + 1: if the character at position room is a space the word before stays whole
    last_space = re.search(r"\s\S*$", text[: room + 1])
    head = text[: last_space.start()].rstrip(" ,;:-–—") if last_space else ""
    return head + ELLIPSIS if head else ""
