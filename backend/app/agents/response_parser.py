"""
Parsing delle risposte JSON degli LLM.

Regola: una risposta o e' valida o non produce nulla. Niente testo di ripiego
e niente testo grezzo nel feed. Il JSON troncato non viene mai "completato":
un post tagliato a meta' e' peggio di nessun post.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_PARSE_FAILED = "parse_failed"
OUTCOME_TRUNCATED = "truncated"
FAILED_OUTCOMES = (OUTCOME_EMPTY, OUTCOME_PARSE_FAILED, OUTCOME_TRUNCATED)

# Il prompt di decide_action chiede un testo solo per queste azioni
ACTIONS_REQUIRING_CONTENT = {"CREATE_POST", "REPOST"}
# Il prompt nomina queste azioni su ogni piattaforma, oltre a available_actions
ACTIONS_NAMED_IN_PROMPT = {"CREATE_POST", "LIKE", "DISLIKE", "REPOST", "DO_NOTHING"}

_FENCED = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)
# Fine di un valore stringa: virgoletta seguita dalla chiave successiva o dalla } finale
_VALUE_END = re.compile(r'"\s*(?:,\s*"[a-zA-Z_]+"\s*:|\}\s*$)')


def _loads_object(text: str, strict: bool = True) -> dict | None:
    try:
        data = json.loads(text, strict=strict)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _repair_field(text: str, key: str) -> str:
    """Esegue l'escape delle virgolette interne non escapate nel valore stringa di `key`."""
    match = re.search(rf'"{key}"\s*:\s*"', text)
    if not match:
        return text
    start = match.end()
    end = _VALUE_END.search(text, start)
    if not end:
        return text
    value = re.sub(r'(?<!\\)"', r'\\"', text[start:end.start()])
    return text[:start] + value + text[end.start():]


def parse_json_object(raw: str | None, repair_fields: Iterable[str] = ()) -> dict | None:
    """Estrae un oggetto JSON da una risposta LLM, o None se non e' recuperabile.

    Ordine: json.loads stretto, poi l'oggetto tra la prima { e l'ultima }, poi la
    riparazione delle virgolette interne nei campi `repair_fields`.
    """
    text = (raw or "").strip()
    fenced = _FENCED.match(text)
    if fenced:
        text = fenced.group(1)
    data = _loads_object(text)
    if data is not None:
        return data
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    # strict=False: gli LLM mettono spesso a capo reali dentro le stringhe
    span = text[start:end + 1]
    data = _loads_object(span, strict=False)
    if data is not None:
        return data
    for key in repair_fields:
        span = _repair_field(span, key)
    return _loads_object(span, strict=False)


def reply_failure(raw: Any) -> str | None:
    """Ritorna OUTCOME_EMPTY o OUTCOME_TRUNCATED se la risposta e' inutilizzabile, altrimenti None."""
    if not raw or not raw.strip():
        return OUTCOME_EMPTY
    if getattr(raw, "finish_reason", None) == "length":
        return OUTCOME_TRUNCATED
    return None


def failed_reply(outcome: str) -> dict:
    """Azione decide_action per una risposta inutilizzabile: nessun post, stato invariato."""
    return {
        "action": "DO_NOTHING",
        "content": "",
        "target_post_id": None,
        "reasoning": outcome,
        "opinion_shift": 0.0,
        "emotional_shift": None,
        "target_agent": None,
        "response_outcome": outcome,
    }


def _looks_like_raw_json(content: str) -> bool:
    return content.startswith("```") or (content.startswith("{") and '"action"' in content)


def parse_agent_reply(raw: Any, available_actions: Iterable[str]) -> dict:
    """Valida la risposta di decide_action. Ritorna sempre un'azione eseguibile dall'engine."""
    failure = reply_failure(raw)
    if failure:
        return failed_reply(failure)

    data = parse_json_object(raw, repair_fields=("content", "reasoning"))
    if data is None:
        return failed_reply(OUTCOME_PARSE_FAILED)

    action = data.get("action")
    action = action.strip().upper() if isinstance(action, str) else ""
    content = data.get("content")
    content = content.strip() if isinstance(content, str) else ""
    if (
        action not in ACTIONS_NAMED_IN_PROMPT.union(available_actions)
        or (action in ACTIONS_REQUIRING_CONTENT and not content)
        or _looks_like_raw_json(content)
    ):
        return failed_reply(OUTCOME_PARSE_FAILED)

    try:
        opinion_shift = float(data.get("opinion_shift") or 0.0)
    except (TypeError, ValueError):
        opinion_shift = 0.0
    emotional_shift = data.get("emotional_shift")
    return {
        **data,
        "action": action,
        "content": content,
        "target_post_id": data.get("target_post_id"),
        "opinion_shift": opinion_shift,
        "emotional_shift": emotional_shift if isinstance(emotional_shift, str) else None,
        "response_outcome": OUTCOME_OK,
    }
