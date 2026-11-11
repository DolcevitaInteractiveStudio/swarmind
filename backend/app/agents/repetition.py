"""An agent does not publish the same post twice.

A critical voice published two nearly identical posts in rounds 4 and 5. Before a post is published it is
compared with the same agent's previous posts (normalised token Jaccard: cheap, no embedding call); above
REPETITION_THRESHOLD the agent is asked once for something new, and a second repetition is not published.
"""
from __future__ import annotations

import re

# Two posts of the same agent with this share of shared words (Jaccard of their word sets) are the same post.
# Different posts of one agent on one topic share their subject words: on test pairs they stay under 0.4;
# a reworded copy sits above 0.6
REPETITION_THRESHOLD = 0.6
# How many of the agent's last posts a new post is compared with
REPETITION_HISTORY = 5
# Words of at least 3 letters: articles and short prepositions carry no content
_WORD = re.compile(r"[^\W\d_]{3,}")


def post_tokens(text: str) -> set[str]:
    """The word set of a post: lower case, typographic apostrophes normalised, numbers and short words out."""
    return {w.lower() for w in _WORD.findall((text or "").replace("’", "'"))}


def jaccard(a: str, b: str) -> float:
    ta, tb = post_tokens(a), post_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def most_similar(text: str, previous: list[str]) -> tuple[float, str | None]:
    """(similarity, post) of the previous post closest to text, or (0.0, None) without previous posts."""
    best, best_post = 0.0, None
    for post in previous:
        score = jaccard(text, post)
        if score > best:
            best, best_post = score, post
    return best, best_post


def repeats(text: str, previous: list[str], threshold: float = REPETITION_THRESHOLD) -> str | None:
    """The previous post that text repeats, or None."""
    score, post = most_similar(text, previous)
    return post if post is not None and score >= threshold else None
