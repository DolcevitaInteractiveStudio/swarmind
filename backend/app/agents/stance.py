"""Stance of an agent toward the change being tested: support | neutral | oppose.

Conviction (opinion_strength) says how firmly an agent holds its position; stance says which position it
holds. A convinced supporter and a convinced critic have the same conviction and opposite stances.

The model answers with the English enum (the language directive keeps enum values in English). The parser
also accepts close variants and the Italian words; anything else becomes "neutral" and the entry is marked
unparsed, so the logs and the report can count it.
"""
from __future__ import annotations

import re

STANCES = ("support", "neutral", "oppose")
DEFAULT_STANCE = "neutral"
SPAWN_ROUND = 0  # round of the stance measured at spawn (initial opinion)

# The JSON value shown to the model, and the line that defines it
STANCE_ENUM = "support | neutral | oppose"
STANCE_DEFINITION = (
    "stance is your position on the change being tested: support (in favour of it), oppose (against it), "
    "neutral (undecided or mixed). It is separate from strength: a convinced critic has stance oppose and a "
    "high strength."
)

_SYNONYMS = {
    "support": ("support", "supports", "supporting", "supportive", "supporter", "in favor", "in favour",
                "favor", "favour", "favorable", "favourable", "pro", "for", "approve", "approves",
                "favorevole", "a favore", "sostegno", "sostiene", "sostenitore", "sostenitrice", "supporto"),
    "neutral": ("neutral", "neutrale", "neutro", "undecided", "indeciso", "indecisa", "mixed", "ambivalent",
                "ambivalente", "unsure", "incerto", "incerta"),
    "oppose": ("oppose", "opposes", "opposed", "opposing", "against", "contro", "contrario", "contraria",
               "contrari", "opposizione", "disapprove", "disapproves"),
}
_LOOKUP = {word: stance for stance, words in _SYNONYMS.items() for word in words}


def parse_stance(value) -> tuple[str, bool]:
    """(stance, recognized). A missing or unknown value is ("neutral", False)."""
    if not isinstance(value, str):
        return DEFAULT_STANCE, False
    text = re.sub(r"[\s_\-]+", " ", value.strip().lower()).strip(" .,;:!\"'`")
    stance = _LOOKUP.get(text)
    return (stance, True) if stance else (DEFAULT_STANCE, False)


def record_stance(agent, value, round_num: int) -> bool:
    """Sets agent.stance and appends {"round", "stance"} to agent.stance_history (with "unparsed": True
    when the value was not recognized). Returns whether the value was recognized."""
    stance, recognized = parse_stance(value)
    entry = {"round": int(round_num), "stance": stance}
    if not recognized:
        entry["unparsed"] = True
    agent.stance = stance
    agent.stance_history.append(entry)
    return recognized


def stance_counts(agents) -> dict:
    """Current stance of the agents: counts per stance, unparsed (last entry) and not measured."""
    counts = dict.fromkeys(STANCES, 0)
    counts.update(unparsed=0, not_measured=0)
    for agent in agents:
        history = getattr(agent, "stance_history", None) or []
        if not history:
            counts["not_measured"] += 1
            continue
        counts[history[-1].get("stance", DEFAULT_STANCE)] += 1
        counts["unparsed"] += bool(history[-1].get("unparsed"))
    return counts
