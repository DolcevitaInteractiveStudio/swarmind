"""Stance metrics of a simulation: deterministic, from the stance history saved with each agent.

- distribution: counts and shares of the last measured stance, natural agents and adversarial agents
  separately (agents never measured are counted apart, not as neutral)
- agreement: share of the majority stance among the natural agents (all agents when no natural agent was
  measured). This is the only "consensus" of the report.
- shift: agents whose stance changed between their first and last measurement, over the agents measured
  at least twice, with the direction (toward support / toward oppose)
- by_segment: the distribution of the natural agents of each Demographer segment (entity_id "segment:<id>"),
  the only per-segment stance figures the report may cite

The readings (thresholds) are in report/postprocess.py, with the other readings of the report.
Simulations saved before the stance measure have no history: {"measured": False}.
"""
from __future__ import annotations

from ..agents.stance import DEFAULT_STANCE, STANCES

_ORDER = {"oppose": 0, "neutral": 1, "support": 2}


def _history(agent) -> list[dict]:
    raw = agent.get("stance_history") if isinstance(agent, dict) else getattr(agent, "stance_history", None)
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if isinstance(entry, dict) and entry.get("stance") in STANCES:
            out.append(entry)
    return out


def _is_adversarial(agent) -> bool:
    return bool(agent.get("is_adversarial", False) if isinstance(agent, dict) else getattr(agent, "is_adversarial", False))


def _distribution(histories: list[list[dict]], index: int) -> dict:
    counts = dict.fromkeys(STANCES, 0)
    measured = unparsed = 0
    for history in histories:
        if not history:
            continue
        entry = history[index]
        counts[entry.get("stance", DEFAULT_STANCE)] += 1
        unparsed += bool(entry.get("unparsed"))
        measured += 1
    shares = {k: (round(v / measured, 4) if measured else 0.0) for k, v in counts.items()}
    return {"counts": counts, "shares": shares, "measured": measured,
            "not_measured": len(histories) - measured, "unparsed": unparsed}


def compute_stance_metrics(agents, segments: list[dict] | None = None) -> dict:
    """Stance distribution, agreement, shift and per-segment distribution. {"measured": False} when no
    agent has a stance. segments: the Demographer's segments (segment_id, label), for the labels."""
    groups: dict[str, list[list[dict]]] = {"natural": [], "adversarial": []}
    by_segment: dict[str, list[list[dict]]] = {}
    for agent in agents or []:
        groups["adversarial" if _is_adversarial(agent) else "natural"].append(_history(agent))
        entity = str((agent.get("entity_id") if isinstance(agent, dict) else getattr(agent, "entity_id", "")) or "")
        if not _is_adversarial(agent) and entity.startswith("segment:"):
            by_segment.setdefault(entity.split(":", 1)[1], []).append(_history(agent))
    if not any(h for histories in groups.values() for h in histories):
        return {"measured": False}

    out: dict = {"measured": True}
    for name, histories in groups.items():
        out[name] = {"agents": len(histories), "final": _distribution(histories, -1),
                     "initial": _distribution(histories, 0)}

    base = "natural" if out["natural"]["final"]["measured"] else "adversarial"
    final = out[base]["final"]
    top_count = max(final["counts"].values())
    leaders = [s for s in STANCES if final["counts"][s] == top_count]
    out["agreement"] = {
        "group": base,
        "share": round(top_count / final["measured"], 4),
        "majority": leaders[0] if len(leaders) == 1 else None,
        "tied": leaders if len(leaders) > 1 else [],
        "measured": final["measured"],
    }

    remeasured = [h for h in groups[base] if len(h) >= 2]
    changed = [h for h in remeasured if h[0]["stance"] != h[-1]["stance"]]
    toward_support = sum(_ORDER[h[-1]["stance"]] > _ORDER[h[0]["stance"]] for h in changed)
    out["shift"] = {
        "group": base,
        "remeasured": len(remeasured),
        "changed": len(changed),
        "share": round(len(changed) / len(remeasured), 4) if remeasured else None,
        "toward_support": toward_support,
        "toward_oppose": len(changed) - toward_support,
    }
    labels = {str(s.get("segment_id")): str(s.get("label") or s.get("segment_id")) for s in segments or []
              if isinstance(s, dict)}
    out["by_segment"] = [
        {"segment_id": seg, "label": labels.get(seg, seg), "agents": len(histories),
         "final": _distribution(histories, -1)}
        for seg, histories in by_segment.items() if any(histories)
    ]
    return out
