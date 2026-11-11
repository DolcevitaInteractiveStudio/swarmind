"""Integration helpers per lo Step 3 del refactor persona-pipeline.

Funzioni di supporto al cablaggio in tasks.py:
  - read_brief_from_disk(path): legge il file di brief con il parser dei documenti caricati
  - extract_domain_context(graph_data): estrae un riassunto testuale dei
    nodi non-PERSON del knowledge graph (concetti, geografie, organizzazioni
    NON agentificate, regolamenti) da iniettare nei prompt PersonaGenerator
    come contesto di dominio.
  - render_subject_card(spec): scheda breve del soggetto del brief, iniettata
    in tutti i prompt rivolti agli agenti.
  - critical_voices_for_spec(spec): voci critiche delle simulazioni senza
    template, pronte per spawn_adversarial_agents.

Tenute separate dal Demographer/PersonaGenerator perche' sono adapter
verso il sistema legacy (state_store + filesystem), non logica di
generazione popolazione.
"""
from __future__ import annotations

import structlog
from pathlib import Path

from ..core.i18n import normalize_language, t, t_value
from ..utils.document_parser import parse_document
from .name_pool import detect_language

log = structlog.get_logger()

SUBJECT_CARD_MAX_CHARS = 450
# Etichette della scheda soggetto: catalogo, chiavi subject_card.*
_SUBJECT_CARD_KEYS = ("subject", "market", "change", "homonyms")
# Limite per riga, non sul totale: un testo lungo non deve far sparire la riga degli omonimi.
# La somma (piu' gli a capo) resta sotto SUBJECT_CARD_MAX_CHARS.
_SUBJECT_CARD_LINE_LIMITS = {"subject": 130, "market": 80, "change": 150, "homonyms": 80}

MAX_CRITICAL_VOICES = 3


def read_brief_from_disk(brief_path: str | Path) -> str:
    """Legge un file di brief con lo stesso parser usato per grafo e KB.

    I brief originali spesso vengono da Word/Outlook in CP1252, raramente
    in UTF-8 puro: l'encoding lo gestisce parse_document, che estrae anche
    il testo di PDF e DOCX invece di decodificarne i byte grezzi.

    Solleva FileNotFoundError se il file non esiste.
    """
    p = Path(brief_path)
    if not p.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")

    text = parse_document(str(p))
    log.debug("brief_read", path=str(p), chars=len(text))
    return text


def _spec_as_dict(spec) -> dict:
    """La spec arriva come PopulationSpec (spawn) o come dict letto da meta.json."""
    if hasattr(spec, "to_dict"):
        return spec.to_dict()
    return spec if isinstance(spec, dict) else {}


def _subject_fields(spec) -> dict:
    subject = _spec_as_dict(spec).get("subject")
    return subject if isinstance(subject, dict) else {}


def _one_line(value) -> str:
    """Testo su una riga. Gli LLM a volte mettono a capo o liste nei campi di testo."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(v for v in value if isinstance(v, str))
    return " ".join(value.split()) if isinstance(value, str) else ""


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")


def subject_language(spec) -> str:
    """Lingua del brief: "en" o "it". Non e' la lingua della simulazione (simulations.language):
    serve dove conta il mercato del brief (pool dei nomi) e, senza lingua, ai tool CLI.

    Usa il campo del Demographer; se manca o non e' riconosciuto deduce dal domain_summary.
    """
    code = _one_line(_subject_fields(spec).get("language")).lower()
    if code.startswith("en"):
        return "en"
    if code.startswith("it"):
        return "it"
    return detect_language(_one_line(_spec_as_dict(spec).get("domain_summary")))


def change_tested(spec, prediction_requirement: str = "", topic: str = "") -> str:
    """What the agents take a stance on: the change of the subject card, else the prediction question,
    else the topic. One line."""
    for value in (_subject_fields(spec).get("change_tested"), prediction_requirement, topic):
        text = _one_line(value)
        if text:
            return text
    return ""


def subject_homonyms(spec) -> list[str]:
    homonyms = _subject_fields(spec).get("homonyms_to_avoid")
    if isinstance(homonyms, str):
        homonyms = [homonyms]
    if not isinstance(homonyms, (list, tuple)):
        return []
    return [text for text in map(_one_line, homonyms) if text]


def render_subject_card(spec, language: str | None = None) -> str:
    """Scheda del soggetto (max ~450 caratteri) nella lingua della simulazione (language),
    o in quella del brief se language manca (tool CLI).

    Il topic non puo' fare questo lavoro: e' il nome del progetto, puo' essere ambiguo
    (una parola comune usata come marchio) e guida anche le query KB e il titolo del report.

    Senza nome e descrizione del soggetto (spec precedenti al campo, campo vuoto) ritorna
    il domain_summary. Vuota se non c'e' nemmeno quello.
    """
    subject = _subject_fields(spec)
    name = _one_line(subject.get("name"))
    what_it_is = _one_line(subject.get("what_it_is"))
    if not (name and what_it_is):
        summary = _one_line(_spec_as_dict(spec).get("domain_summary"))
        return _clip(summary, SUBJECT_CARD_MAX_CHARS)

    market = (_one_line(subject.get("market")), _one_line(subject.get("sector")))
    values = {
        "subject": f"{name}, {what_it_is}",
        "market": "; ".join(v for v in market if v),
        "change": _one_line(subject.get("change_tested")),
        "homonyms": "; ".join(subject_homonyms(spec)),
    }
    card_language = _card_language(spec, language)
    labels = {key: t(card_language, f"subject_card.{key}") for key in _SUBJECT_CARD_KEYS}
    lines = []
    for key, value in values.items():
        if value:
            line = f"{labels[key]}: {value}".rstrip(" .")
            lines.append(_clip(line, _SUBJECT_CARD_LINE_LIMITS[key] - 1) + ".")
    return "\n".join(lines)


def _card_language(spec, language: str | None) -> str:
    """Lingua della simulazione se data, altrimenti quella del brief (tool CLI, chiamate senza lingua)."""
    return normalize_language(language) or ("en" if subject_language(spec) == "en" else "it")


def _text_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [text for text in map(_one_line, value) if text]


def _complete_critical_voice(raw) -> dict | None:
    """Spec completa per spawn_adversarial_agents, o None se la voce non e' utilizzabile.

    Solo campi noti: un valore malformato dell'LLM farebbe fallire lo spawn di tutte le voci,
    custom comprese. communication_style presente evita la chiamata LLM di arricchimento.
    """
    if not isinstance(raw, dict):
        return None
    voice = {key: _one_line(raw.get(key)) for key in ("name", "role", "background")}
    voice.update({key: _text_list(raw.get(key)) for key in ("core_beliefs", "fears", "motivations")})
    if not all(voice[key] for key in ("name", "role", "background", "core_beliefs")):
        return None
    voice["communication_style"] = "direct"
    # Il default di spawn_adversarial_agents e' in italiano e cita il topic, cioe' il nome del progetto
    voice["initial_opinion_on_topic"] = voice["core_beliefs"][0]
    return voice


def critical_voices_for_spec(spec, simulation_id: str | None = None,
                             language: str | None = None) -> list[dict]:
    """Voci critiche di una simulazione senza template, nella lingua della simulazione.

    Usa quelle proposte dal Demographer; se mancano o nessuna e' valida, il set neutro del
    catalogo (critical_voices.fallback: vale per qualsiasi soggetto, niente lessico di settore)
    e il log critical_voices_fallback.
    """
    raw = _spec_as_dict(spec).get("critical_voices")
    raw = raw if isinstance(raw, list) else []
    voices = [voice for voice in map(_complete_critical_voice, raw) if voice]
    if voices:
        return voices[:MAX_CRITICAL_VOICES]

    language = _card_language(spec, language)
    log.warning(
        "critical_voices_fallback",
        simulation_id=simulation_id,
        language=language,
        received=len(raw),
    )
    return [_complete_critical_voice(voice) for voice in t_value(language, "critical_voices.fallback")]


def extract_domain_context(
    graph_data: dict,
    max_entities_per_type: int = 12,
    max_total_chars: int = 3000,
) -> str:
    """Estrae un riassunto testuale del knowledge graph come contesto di
    dominio per il PersonaGenerator.

    Esclude i nodi di tipo PERSON (raramente presenti, e comunque non
    rilevanti come contesto: il PersonaGenerator GENERA persone, non le
    riusa). Include CONCEPT, ORG, PLACE, FINANCIAL, EVENT raggruppati
    per tipo.

    Lo scopo NON e' costruire una popolazione (quello lo fa il
    Demographer dal brief), ma fornire al PersonaGenerator riferimenti
    concreti che le sue personas possono citare in modo realistico:
    competitor noti, regolamenti pertinenti, geografie del dominio.

    Args:
        graph_data: dict serializzato da KnowledgeGraph.to_dict()
        max_entities_per_type: cap per evitare contesti troppo lunghi
        max_total_chars: hard cap sulla lunghezza totale del testo

    Returns:
        Stringa multilinea formattata, raggruppata per tipo di entita'.
        Vuota se il graph_data non ha nodi utilizzabili.
    """
    nodes = graph_data.get("nodes", [])
    if not nodes:
        return ""

    # Raggruppa per tipo, esclude PERSON
    by_type: dict[str, list[dict]] = {}
    for n in nodes:
        ntype = (n.get("type") or "UNKNOWN").upper()
        if ntype == "PERSON":
            continue
        by_type.setdefault(ntype, []).append(n)

    if not by_type:
        return ""

    # Ordine di priorita' per i tipi: prima ORG (competitor reali utili),
    # poi CONCEPT, PLACE, FINANCIAL, EVENT, UNKNOWN
    type_order = ["ORG", "CONCEPT", "PLACE", "FINANCIAL", "EVENT", "UNKNOWN"]
    sections: list[str] = []
    for ntype in type_order:
        items = by_type.get(ntype, [])
        if not items:
            continue
        items = items[:max_entities_per_type]
        formatted = []
        for item in items:
            label = item.get("label", item.get("id", "?"))
            desc = item.get("description", "")
            if desc:
                formatted.append(f"  - {label}: {desc[:120]}")
            else:
                formatted.append(f"  - {label}")
        sections.append(f"{ntype}:\n" + "\n".join(formatted))

    text = "\n\n".join(sections)
    if len(text) > max_total_chars:
        text = text[:max_total_chars] + "\n[...truncated]"

    log.debug(
        "domain_context_extracted",
        types_included=list(by_type.keys()),
        entities_count=sum(len(v) for v in by_type.values()),
        chars=len(text),
    )
    return text
