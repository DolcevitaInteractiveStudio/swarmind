"""
Post-processing deterministico del report: le parti che appartengono al codice, non al modello.

- Quota di post adversarial: una sola frase canonica, calcolata dai contatori del run. Le varianti
  scritte dal modello (riconosciute dal significato, non dal testo esatto) vengono tolte.
- Sezione "Dinamiche del Dibattito": in ogni report, con un blocco deterministico che riporta le
  tre metriche di metrics.py, i valori e l'etichetta di interpretazione. Il modello scrive solo la
  lettura sotto il blocco; se salta la sezione, la sezione viene aggiunta con il solo blocco.
- Niente falsa precisione: gli scenari non hanno probabilita' numeriche (tolte se il modello le
  scrive) e il livello di confidenza lo calcola il codice dal campione e dalla stabilita'.

Il report e' nella lingua della simulazione: il testo fisso viene dal catalogo (core.i18n, locales),
i numeri hanno la virgola decimale in italiano e il punto in inglese.
"""
from __future__ import annotations

import functools
import re

from ..agents.stance import STANCES
from ..core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t, t_value

# ── Formattazione numeri ──────────────────────────────────────────────────────

def fmt_number(value: float, digits: int = 1, lang: str = DEFAULT_LANGUAGE) -> str:
    text = f"{float(value):.{digits}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text.replace(".", ",") if lang == "it" else text


def fmt_signed(value: float, digits: int = 1, lang: str = DEFAULT_LANGUAGE) -> str:
    text = fmt_number(value, digits, lang)
    return text if text.startswith("-") or float(value) <= 0 else "+" + text


def fmt_pct(fraction: float, digits: int = 1, lang: str = DEFAULT_LANGUAGE) -> str:
    return fmt_number(float(fraction) * 100, digits, lang) + "%"


# ── Sezioni markdown ──────────────────────────────────────────────────────────

_TOP_HEADING = re.compile(r"^(#{1,2})\s+(.*\S)\s*$")
_ANY_HEADING = re.compile(r"^\s*#{1,6}\s")

def _catalog_alternatives(key: str) -> str:
    """Regex che riconosce il testo della chiave in tutte le lingue del catalogo (senza ** e :)."""
    texts = {t(lang, key).strip("*: ").strip() for lang in SUPPORTED_LANGUAGES}
    return "|".join(re.escape(text) for text in sorted(texts))


def debate_title(lang: str = DEFAULT_LANGUAGE) -> str:
    return t(lang, "debate.title")


DEBATE_HEADING_RE = re.compile(
    rf"dinamiche\s+del\s+dibattito|debate\s+dynamics|{_catalog_alternatives('debate.title')}", re.I)
SCENARIO_HEADING_RE = re.compile(
    rf"scenari|{_catalog_alternatives('report.headings.scenario_analysis')}", re.I)
# La sezione si chiama "Reazione più plausibile" / "Most plausible reaction"; i report salvati prima del cambio di
# nome hanno "Previsione" / "Prediction" e restano riconosciuti.
PREDICTION_HEADING_RE = re.compile(
    rf"^(prediction|previsione|predizione|{_catalog_alternatives('report.headings.prediction')})\b", re.I)
CONFIDENCE_HEADING_RE = re.compile(
    rf"confidence|confidenza|affidabilit|{_catalog_alternatives('report.headings.confidence_assessment')}", re.I)
APPENDIX_HEADING_RE = re.compile(
    rf"appendice|appendix|methodolog|metodologic|{_catalog_alternatives('report.headings.appendix')}", re.I)
SIM_METRICS_HEADING_RE = re.compile(
    rf"simulation\s+metrics|metriche\s+(?:della\s+)?simulazione|"
    rf"{_catalog_alternatives('report.headings.simulation_metrics')}", re.I)
LANDSCAPE_HEADING_RE = re.compile(
    rf"opinion\s+landscape|panorama\s+delle\s+opinioni|{_catalog_alternatives('report.headings.opinion_landscape')}", re.I)


def section_bounds(lines: list[str], title_re: re.Pattern) -> tuple[int, int] | None:
    """(riga del titolo '## ...', riga dove finisce la sezione) della prima sezione che corrisponde."""
    for i, line in enumerate(lines):
        m = _TOP_HEADING.match(line)
        if m and len(m.group(1)) == 2 and title_re.search(m.group(2)):
            end = next((j for j in range(i + 1, len(lines)) if _TOP_HEADING.match(lines[j])), len(lines))
            return i, end
    return None


def _tidy(md: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def replace_lines_containing(md: str, needle: str, new_line: str) -> tuple[str, int]:
    """Sostituisce ogni riga che contiene needle (senza distinguere maiuscole). Ritorna (report, righe)."""
    lines = md.split("\n")
    hits = [i for i, line in enumerate(lines) if needle.lower() in line.lower()]
    for i in hits:
        lines[i] = new_line
    return "\n".join(lines), len(hits)


# ── Metriche della simulazione: tabella del codice, etichette del lettore ─────

# Una sola tabella di soglie per le letture delle metriche: la tabella del report, il prompt, i valori dati
# al modello (compute_consensus, blocco CONFIDENCE LEVEL), la stabilita' della confidenza e i post-check.
ENTROPY_LOW_BELOW = 0.3   # opinion_entropy < 0.3: convergenza forte (low)
ENTROPY_HIGH_ABOVE = 0.6  # 0.3 <= opinion_entropy <= 0.6: divergenza moderata (mid); > 0.6: divergenza alta (high)
# Uniformita' della convinzione: variance di opinion_strength. Dice quanto e' simile l'intensita' delle
# convinzioni, NON se gli agenti sono d'accordo: un sostenitore convinto e un critico convinto hanno la
# stessa convinzione. Non e' mai chiamata consenso.
CONVICTION_UNIFORMITY_HIGH_BELOW = 0.05    # variance < 0.05: high
CONVICTION_UNIFORMITY_MEDIUM_BELOW = 0.15  # 0.05 <= variance < 0.15: medium; >= 0.15: low
# Consenso = accordo sulla posizione (stance) verso il cambiamento: quota degli agenti naturali con la
# posizione di maggioranza. Con tre posizioni una divisione casuale da' circa un terzo: sopra la meta' una
# posizione prevale, da tre su quattro c'e' accordo largo. Due posizioni a pari merito: basso.
STANCE_CONSENSUS_HIGH_FROM = 0.75    # >= 75%: high
STANCE_CONSENSUS_MEDIUM_FROM = 0.5   # 50-75%: medium; < 50% (o parita'): low
# Spostamento: quota degli agenti misurati almeno due volte che hanno cambiato posizione tra la prima e
# l'ultima misura. Su 10 agenti rimisurati un cambio (10%) e' rumore, 2-3 uno spostamento, 4+ uno ampio.
STANCE_SHIFT_MODERATE_FROM = 0.15    # < 15%: stable
STANCE_SHIFT_LARGE_FROM = 0.35       # 15-35%: moderate; >= 35%: large
# "Ampio" (e "posizioni stabili" come base di una confidenza alta) solo con almeno 10 agenti rimisurati.
# Su n agenti un solo cambio sposta la quota di 1/n: con 8 agenti 3 cambi fanno 37,5% (ampio) e 2 fanno
# 25% (moderato), un agente decide la lettura. Da 10 un agente vale al massimo 10 punti, meno dei 20
# punti tra le soglie moderato (15%) e ampio (35%). Sotto: al massimo "moderato", con il conteggio.
STANCE_SHIFT_MIN_REMEASURED = 10
# Posizione per segmento in percentuale solo con almeno 3 agenti naturali nel segmento. Con 1 agente ogni
# quota e' 0% o 100%, con 2 e' 0/50/100%: una sola persona generata decide il dato. Da 3 un agente non e'
# piu' la meta' del segmento. Sotto, il report riceve i conteggi ("1 su 1 contrario") e non generalizza.
SEGMENT_STANCE_MIN_AGENTS = 3


def entropy_reading(entropy: float | None) -> str | None:
    """low | mid | high (chiavi report.entropy.*), None senza valore."""
    if entropy is None:
        return None
    return "low" if entropy < ENTROPY_LOW_BELOW else "mid" if entropy <= ENTROPY_HIGH_ABOVE else "high"


def conviction_uniformity_reading(variance: float) -> str:
    """high | medium | low (chiavi report.conviction_uniformity_levels.*) dalla variance di opinion_strength."""
    return ("high" if variance < CONVICTION_UNIFORMITY_HIGH_BELOW
            else "medium" if variance < CONVICTION_UNIFORMITY_MEDIUM_BELOW else "low")


def stance_measured(stance: dict | None) -> bool:
    return bool(stance and stance.get("measured"))


def stance_consensus_level(stance: dict | None) -> str | None:
    """high | medium | low (chiavi report.consensus_levels.*) dall'accordo sulla posizione; None se la
    posizione non e' stata misurata. Nessuna maggioranza (parita'): low."""
    if not stance_measured(stance):
        return None
    agreement = stance["agreement"]
    if not agreement.get("majority"):
        return "low"
    share = agreement["share"]
    return ("high" if share >= STANCE_CONSENSUS_HIGH_FROM
            else "medium" if share >= STANCE_CONSENSUS_MEDIUM_FROM else "low")


def stance_shift_reading(share: float | None, remeasured: int | None = None) -> str | None:
    """stable | moderate | large (chiavi report.stance.shift_readings.*); None senza agenti rimisurati.
    Con remeasured sotto STANCE_SHIFT_MIN_REMEASURED "large" diventa "moderate"."""
    if share is None:
        return None
    reading = ("stable" if share < STANCE_SHIFT_MODERATE_FROM
               else "moderate" if share < STANCE_SHIFT_LARGE_FROM else "large")
    if reading == "large" and remeasured is not None and remeasured < STANCE_SHIFT_MIN_REMEASURED:
        return "moderate"
    return reading


def _shift_of(stance: dict) -> tuple[str | None, bool]:
    """(lettura dello spostamento, True se limitata a "moderate" per pochi agenti rimisurati)."""
    shift = stance["shift"]
    reading = stance_shift_reading(shift.get("share"), shift.get("remeasured"))
    return reading, reading != stance_shift_reading(shift.get("share"))


def stance_shift_label(stance: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """"spostamento moderato (3 su 8 agenti rimisurati)", o "spostamento non misurabile"."""
    reading, _ = _shift_of(stance)
    if reading is None:
        return t(lang, "report.stance.shift_unmeasurable")
    shift = stance["shift"]
    return t(lang, "report.stance.shift_with_count", reading=t(lang, f"report.stance.shift_readings.{reading}"),
             changed=shift["changed"], remeasured=shift["remeasured"])


def stance_reading_rules() -> str:
    """Le soglie di consenso e spostamento, per il modello: le stesse della tabella e della confidenza."""
    pct = lambda v: f"{round(v * 100)}%"  # noqa: E731
    return (f"consensus_level = share of the natural agents holding the most common stance (a majority only "
            f"above 50%; at 50% or less it is a plurality): high from "
            f"{pct(STANCE_CONSENSUS_HIGH_FROM)}, medium from {pct(STANCE_CONSENSUS_MEDIUM_FROM)}, low below "
            f"(or when two stances tie). shift = share of the agents measured at least twice whose stance "
            f"changed between first and last measurement: stable below {pct(STANCE_SHIFT_MODERATE_FROM)}, "
            f"moderate from {pct(STANCE_SHIFT_MODERATE_FROM)}, large from {pct(STANCE_SHIFT_LARGE_FROM)} and only "
            f"with at least {STANCE_SHIFT_MIN_REMEASURED} re-measured agents (fewer: at most moderate). Always give "
            f"the count of re-measured agents with the shift.")


def segment_count_text(seg: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """Posizione di un segmento piccolo in conteggi: "1 su 1 contrario", "1 su 2 a favore, 1 su 2 neutrale"."""
    final = seg["final"]
    return ", ".join(t(lang, "report.stance.count_share", count=final["counts"][s], total=final["measured"],
                       label=_stance_label(s, lang)) for s in STANCES if final["counts"][s])


def _stance_label(stance_value: str, lang: str) -> str:
    return t(lang, f"report.stance_values.{stance_value}")


def stance_distribution_text(dist: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """"a favore 3 (21,4%) · neutrale 4 (28,6%) · contrario 7 (50,0%)", con gli agenti non misurati e le
    risposte non interpretate (contate come neutrali) tra parentesi."""
    text = " · ".join(t(lang, "report.stance.share", label=_stance_label(s, lang), count=dist["counts"][s],
                        pct=fmt_pct(dist["shares"][s], 1, lang)) for s in STANCES)
    extras = []
    if dist.get("not_measured"):
        extras.append(t(lang, "report.stance.agents_not_measured", count=dist["not_measured"]))
    if dist.get("unparsed"):
        extras.append(t(lang, "report.stance.unparsed", count=dist["unparsed"]))
    return text + (f" ({'; '.join(extras)})" if extras else "")


def stance_consensus_text(stance: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """"medio (50,0% contrario)", o "basso (nessuna maggioranza: ...)" con due posizioni a pari merito."""
    level = t(lang, f"report.consensus_levels.{stance_consensus_level(stance)}")
    agreement = stance["agreement"]
    share = fmt_pct(agreement["share"], 1, lang)
    if agreement.get("majority"):
        return t(lang, "report.stance.consensus", level=level, pct=share,
                 stance=_stance_label(agreement["majority"], lang))
    return t(lang, "report.stance.consensus_tie", level=level, pct=share,
             stances=" / ".join(_stance_label(s, lang) for s in agreement.get("tied", [])))


def stance_shift_text(stance: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    shift = stance["shift"]
    reading, capped = _shift_of(stance)
    if reading is None:
        return t(lang, "report.stance.shift_none")
    return t(lang, "report.stance.shift", changed=shift["changed"], remeasured=shift["remeasured"],
             toward_support=shift["toward_support"], toward_oppose=shift["toward_oppose"],
             cap_note=t(lang, "report.stance.shift_cap_note", min=STANCE_SHIFT_MIN_REMEASURED) if capped else "",
             reading=t(lang, f"report.stance.shift_readings.{reading}"))


def stance_rows(stance: dict | None, lang: str = DEFAULT_LANGUAGE) -> list[tuple[str, str]]:
    """Righe della tabella delle metriche sulla posizione. Senza misura: una sola riga che lo dice."""
    if not stance_measured(stance):
        return [(t(lang, "report.labels.stance"), t(lang, "report.stance.not_measured"))]
    rows = []
    for group in ("natural", "adversarial"):
        if stance[group]["agents"]:
            rows.append((t(lang, f"report.labels.stance_{group}"), stance_distribution_text(stance[group]["final"], lang)))
    group = t(lang, f"report.stance.groups.{stance['agreement']['group']}")
    rows.append((f"{t(lang, 'report.labels.consensus_level')} ({group})", stance_consensus_text(stance, lang)))
    rows.append((t(lang, "report.labels.stance_shift"), stance_shift_text(stance, lang)))
    return rows


def stance_observation(stance: dict | None, lang: str = DEFAULT_LANGUAGE) -> dict:
    """La posizione per il modello del report (compute_consensus): valori, etichette e regole di lettura."""
    if not stance_measured(stance):
        return {"measured": False,
                "note": "Stance was not measured in this simulation (created before the stance measure). Write "
                        "that the stance was not measured and do not write about consensus at all."}

    def group(name):
        g = stance[name]
        dist = g["final"]
        return {"agents": g["agents"], "measured": dist["measured"], "not_measured": dist["not_measured"],
                "unparsed_counted_as_neutral": dist["unparsed"],
                "counts": dist["counts"], "shares_pct": {k: round(v * 100, 1) for k, v in dist["shares"].items()},
                "first_measurement_counts": g["initial"]["counts"],
                "summary_label": stance_distribution_text(dist, lang)}

    level = stance_consensus_level(stance)
    agreement = stance["agreement"]
    shift = stance["shift"]
    reading, capped = _shift_of(stance)
    by_segment = []
    for seg in stance.get("by_segment") or []:
        row = {"segment": seg["label"], "agents": seg["agents"], "measured": seg["final"]["measured"],
               "counts": seg["final"]["counts"]}
        if seg["agents"] >= SEGMENT_STANCE_MIN_AGENTS:
            row.update(shares_pct={k: round(v * 100, 1) for k, v in seg["final"]["shares"].items()},
                       summary_label=stance_distribution_text(seg["final"], lang))
        else:
            row.update(too_few_agents_for_percentages=True, summary_label=segment_count_text(seg, lang))
        by_segment.append(row)
    return {
        "measured": True,
        "definition": "each agent's position on the change being tested (support / neutral / oppose), measured "
                      "at spawn and at each opinion refresh; natural agents and critical voices are separate",
        "stance_labels": {s: _stance_label(s, lang) for s in STANCES},
        "natural_agents": group("natural"),
        "critical_voices": group("adversarial"),
        "consensus_level": level,
        "consensus_level_label": t(lang, f"report.consensus_levels.{level}"),
        "consensus_of": agreement["group"],
        # The most common stance: a majority only above 50% (at 50% or less it is a plurality, never a majority)
        "most_common_stance": agreement.get("majority"),
        "most_common_share_pct": round(agreement["share"] * 100, 1),
        "most_common_is_majority": bool(agreement.get("majority")) and agreement["share"] > 0.5,
        "consensus_summary_label": stance_consensus_text(stance, lang),
        "shift": {**shift, "reading": reading, "capped_for_few_remeasured": capped,
                  "reading_label": t(lang, f"report.stance.shift_readings.{reading}") if reading else None,
                  "summary_label": stance_shift_text(stance, lang)},
        # Stance per Demographer segment, natural agents only: the only per-segment stance figures allowed
        "by_segment": by_segment,
        "by_segment_note": (f"stance computed by the system for each segment of the natural agents. Percentages only "
                            f"for segments with at least {SEGMENT_STANCE_MIN_AGENTS} agents; smaller segments have "
                            f"counts only (cite them as counts, e.g. \"1 of 1 oppose\", and do not generalise from "
                            f"them). Never give a segment the shares of all natural agents. A share of 50% or less "
                            f"is not a majority"),
        "reading_rules": stance_reading_rules(),
    }


def entropy_label(entropy: float | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """La lettura di opinion_entropy nella lingua del report ("" senza valore)."""
    reading = entropy_reading(entropy)
    return t(lang, f"report.entropy.{reading}") if reading else ""


def entropy_threshold_lines(lang: str = DEFAULT_LANGUAGE) -> str:
    """Le soglie della regola ENTROPY INTERPRETATION del prompt, dalla stessa tabella."""
    low, high = fmt_number(ENTROPY_LOW_BELOW, 1, "en"), fmt_number(ENTROPY_HIGH_ABOVE, 1, "en")
    rows = ((f"entropy < {low} ", "low"), (f"entropy {low}-{high}", "mid"), (f"entropy > {high} ", "high"))
    return "\n".join(f'      - {cond} → "{t(lang, f"report.entropy.{k}")}" ({t(lang, f"report.entropy.{k}_meaning")})'
                     for cond, k in rows)


def fix_entropy_readings(md: str, entropy: float | None, lang: str = DEFAULT_LANGUAGE) -> tuple[str, int]:
    """Il testo usa la stessa lettura dell'entropia della tabella: un'altra lettura (es. "divergenza
    moderata" con 0,644) diventa quella calcolata. Le frasi su un round specifico, l'appendice e il codice
    restano come sono."""
    reading = entropy_reading(entropy)
    if not md or reading is None:
        return md, 0
    right = t(lang, f"report.entropy.{reading}")
    wrong = [t(lang, f"report.entropy.{k}") for k in ("low", "mid", "high") if k != reading]
    pattern = re.compile(r"(?i)\b(" + "|".join(re.escape(w) for w in wrong) + r")\b")
    lines = md.split("\n")
    appendix = section_bounds(lines, APPENDIX_HEADING_RE)
    fixed, in_code = 0, False

    def repl(m):
        nonlocal fixed
        fixed += 1
        return right[:1].upper() + right[1:] if m.group(1)[:1].isupper() else right

    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code or (appendix and appendix[0] <= i < appendix[1]):
            continue
        sentences = _SENT_SPLIT.split(line)
        lines[i] = " ".join(s if _ROUND_SPECIFIC.search(_LAST_ROUND.sub("", s)) else pattern.sub(repl, s)
                            for s in sentences)
    return ("\n".join(lines), fixed) if fixed else (md, 0)


def simulation_metrics_table(values: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """Tabella "Simulation Metrics" con le etichette della lingua del report e i numeri formattati.

    values: rounds, agents, posts, stance (report/stance_metrics.compute_stance_metrics), conviction_uniformity
    (high|medium|low, dalla variance), mean_opinion_strength, variance, entropy (ultimo round). Un valore
    mancante diventa "n/a" del catalogo. "Consenso" e' solo l'accordo sulla posizione; la variance della
    convinzione e' "uniformita' della convinzione".
    """
    na = t(lang, "debate.not_available")

    def num(key, digits=3):
        v = values.get(key)
        return fmt_number(v, digits, lang) if isinstance(v, (int, float)) else na

    level = values.get("conviction_uniformity")
    uniformity = t(lang, f"report.conviction_uniformity_levels.{level}") if level in ("high", "medium", "low") else na
    entropy = values.get("entropy")
    entropy_text = num("entropy")
    if isinstance(entropy, (int, float)):
        entropy_text += f" ({entropy_label(entropy, lang)})"
    label = lambda key: t(lang, f"report.labels.{key}")  # noqa: E731
    rows = [
        (label("rounds"), str(values.get("rounds", na))),
        (label("agents"), str(values.get("agents", na))),
        (label("total_posts"), str(values.get("posts", na))),
        *stance_rows(values.get("stance"), lang),
        (label("conviction_uniformity"), uniformity),
        (label("mean_conviction"), num("mean_opinion_strength")),
        (label("variance"), num("variance")),
        (label("opinion_entropy"), entropy_text),
    ]
    table = [f"| {t(lang, 'report.metrics_table.metric')} | {t(lang, 'report.metrics_table.value')} |", "|---|---|"]
    table += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(table)


def ensure_metrics_table(md: str, table: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, dict]:
    """La sezione Simulation Metrics contiene solo la tabella del codice: le tabelle del modello si
    tolgono, il suo testo resta sotto la tabella. Senza la sezione, viene aggiunta prima del panorama
    delle opinioni (o dopo il titolo). Ritorna (report, {"outcome", "tables_removed"})."""
    if not md or not table:
        return md, {"outcome": "skipped", "tables_removed": 0}
    lines = md.split("\n")
    bounds = section_bounds(lines, SIM_METRICS_HEADING_RE)
    if bounds:
        start, end = bounds
        body = lines[start + 1:end]
        kept = [line for line in body if not line.strip().startswith("|")]
        removed = sum(1 for i, line in enumerate(body) if line.strip().startswith("|")
                      and (i == 0 or not body[i - 1].strip().startswith("|")))
        text = "\n".join(kept).strip("\n")
        # The heading of the report language, whatever the model wrote
        heading = f"## {t(lang, 'report.headings.simulation_metrics')}"
        section = [heading, "", table, ""] + ([text, ""] if text.strip() else [])
        lines[start:end] = section
        return _tidy("\n".join(lines)), {"outcome": "table_replaced", "tables_removed": removed}
    section = [f"## {t(lang, 'report.headings.simulation_metrics')}", "", table, ""]
    for title_re in (LANDSCAPE_HEADING_RE, DEBATE_HEADING_RE, SCENARIO_HEADING_RE):
        anchor = section_bounds(lines, title_re)
        if anchor:
            lines[anchor[0]:anchor[0]] = section
            return _tidy("\n".join(lines)), {"outcome": "section_added", "tables_removed": 0}
    first_h1 = next((i for i, line in enumerate(lines) if re.match(r"^#\s", line)), None)
    at = first_h1 + 1 if first_h1 is not None else 0
    lines[at:at] = [""] + section
    return _tidy("\n".join(lines)), {"outcome": "section_added", "tables_removed": 0}


# ── Nomi tecnici solo nell'appendice ──────────────────────────────────────────

# English enum values that are also Italian words: never replaced in an Italian report
_ITALIAN_HOMOGRAPHS = {"positive", "negative"}


def localize_field_names(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, int]:
    """Fuori dall'appendice metodologica i nomi dei campi (mean_opinion_strength, opinion_entropy...)
    diventano le parole del lettore (report.field_words); in un report italiano anche i valori inglesi
    degli stati emotivi (curious -> curioso). Codice e appendice restano come sono. Ritorna (report, sostituzioni)."""
    if not md:
        return md, 0
    words = t_value(lang, "report.field_words")
    adv_word = words.pop("is_adversarial")
    patterns = [(re.compile(r"\(\s*is_adversarial\s*(?:=|:)\s*(?:true|True)\s*\)"), f"({adv_word})"),
                (re.compile(r"\bis_adversarial\s*(?:=|:)\s*(?:true|True)\b"), adv_word)]
    # Longest first: mean_opinion_strength before opinion_strength
    for field in sorted(words, key=len, reverse=True):
        patterns.append((re.compile(rf"`?\b{re.escape(field)}\b`?"), words[field]))
    if lang == "it":
        states = {k: v for k, v in t_value(lang, "report.emotional_states").items() if k not in _ITALIAN_HOMOGRAPHS}
        alt = "|".join(re.escape(k) for k in sorted(states, key=len, reverse=True))
        state_re = re.compile(rf"\b({alt})\b", re.I)
    else:
        states, state_re = {}, None
    lines = md.split("\n")
    appendix = section_bounds(lines, APPENDIX_HEADING_RE)
    count, in_code = 0, False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code or (appendix and appendix[0] <= i < appendix[1]):
            continue
        new = line
        for pattern, word in patterns:
            new, n = pattern.subn(word, new)
            count += n
        if state_re:
            def repl(m):
                label = states[m.group(1).lower()]
                return label[:1].upper() + label[1:] if m.group(1)[:1].isupper() else label
            new, n = state_re.subn(repl, new)
            count += n
        lines[i] = new
    return ("\n".join(lines), count) if count else (md, 0)


# ── Quota di post adversarial ─────────────────────────────────────────────────

SHARE_HEADING_RE = re.compile(
    rf"^\s*\*\*\s*(?:{_catalog_alternatives('report.adversarial_note_heading')})\s*:?\s*\*\*", re.I)
_BOLD_LABEL_LINE = re.compile(r"^\s*\*\*[^*\n]{2,80}\*\*\s*:?\s*$")

_SHARE_LABEL = re.compile(
    r"quota\s+(?:di|dei)\s+post\s+(?:adversarial|avversar\w*)|adversarial\s+post\s+share|"
    r"share\s+of\s+adversarial\s+posts", re.I)
_ADV_WORD = re.compile(r"advers|avversar", re.I)
_POST_WORD = re.compile(r"\bposts?\b", re.I)
_SHARE_FIGURE = re.compile(r"\d+(?:[.,]\d+)?\s*%|\b\d+\s+(?:post\s+)?(?:su|of|out\s+of)\s+\d+\b", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"«(*_]*[A-ZÀ-Ý])")
_LINE_PREFIX = re.compile(r"^(\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)?)(.*)$")


def adversarial_share_sentence(stats: dict | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """La frase canonica con la quota reale di post adversarial (contatori salvati a fine run)."""
    if not stats:
        return t(lang, "report.share.not_recorded")
    if not stats.get("adversarial_agents"):
        return t(lang, "report.share.none")
    return t(
        lang, "report.share.full",
        share=fmt_pct(stats["share"], 1, lang),
        adversarial_posts=stats["adversarial_posts"],
        posts=stats["posts"],
        adversarial_agents=stats["adversarial_agents"],
        total_agents=stats["total_agents"],
        cap=fmt_pct(stats["cap"], 1, lang),
    )


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def _is_share_sentence(sentence: str, canonical: set[str]) -> bool:
    if _norm(sentence) in canonical:
        return True
    if _SHARE_LABEL.search(sentence):
        return True
    return bool(_ADV_WORD.search(sentence) and _POST_WORD.search(sentence) and _SHARE_FIGURE.search(sentence))


def remove_share_variants(md: str, canonical_sentence: str) -> tuple[str, int]:
    """Toglie ogni frase sulla quota di post adversarial (anche quella canonica). Tabelle e titoli restano."""
    canonical = {_norm(s) for s in _SENT_SPLIT.split(canonical_sentence) if _norm(s)}
    out, removed, in_code = [], 0, False
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            out.append(line)
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        sentences = _SENT_SPLIT.split(body)
        kept = [s for s in sentences if not _is_share_sentence(s, canonical)]
        if len(kept) == len(sentences):
            out.append(line)
            continue
        removed += len(sentences) - len(kept)
        rest = " ".join(kept).strip()
        if rest.strip("*_ :"):
            out.append(prefix + rest)
    return "\n".join(out), removed


def insert_share_sentence(md: str, sentence: str) -> tuple[str, str]:
    """Mette la frase dopo il paragrafo 'Natura degli agenti adversarial', o in fondo all'appendice/report."""
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if SHARE_HEADING_RE.match(line):
            j = i + 1
            while (j < len(lines) and lines[j].strip() and not _ANY_HEADING.match(lines[j])
                   and not _BOLD_LABEL_LINE.match(lines[j]) and lines[j].strip() != "---"):
                j += 1
            lines.insert(j, sentence)
            return "\n".join(lines), "adversarial_note"
    bounds = section_bounds(lines, APPENDIX_HEADING_RE)
    if bounds:
        end = bounds[1]
        while end > bounds[0] + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", sentence]
        return "\n".join(lines), "appendix_end"
    return f"{md.rstrip()}\n\n{sentence}\n", "report_end"


def ensure_share_sentence(md: str, sentence: str) -> tuple[str, dict]:
    """Nel report resta esattamente una frase sulla quota: quella canonica."""
    if not md:
        return md, {"removed": 0, "placed": None}
    cleaned, removed = remove_share_variants(md, sentence)
    placed_md, placed = insert_share_sentence(cleaned, sentence)
    return _tidy(placed_md), {"removed": removed, "placed": placed}


# ── Dinamiche del Dibattito ───────────────────────────────────────────────────

def debate_block_head(lang: str = DEFAULT_LANGUAGE) -> str:
    return t(lang, "debate.block_head")


def _interp_label(code: str | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Etichetta di interpretazione di una metrica (debate.labels)."""
    labels = t_value(lang, "debate.labels")
    return labels.get(code or "", labels["insufficient_data"])


def _meaning(description: str) -> str:
    """La descrizione di metrics.py senza la parte numerica tra parentesi (formattata qui con la virgola)."""
    head, sep, tail = (description or "").partition("): ")
    text = tail if sep else description or ""
    return text[:1].upper() + text[1:] if text else ""


def debate_metrics_block(metrics: dict | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Tabella deterministica con le tre metriche, i valori e l'interpretazione."""
    if not metrics:
        return debate_block_head(lang) + "\n\n" + t(lang, "debate.unavailable")
    pd = metrics.get("polarization_delta") or {}
    ec = metrics.get("echo_chamber_index") or {}
    inf = metrics.get("information_diversity") or {}
    n = lambda v, d=3: fmt_number(v, d, lang)  # noqa: E731

    na = t(lang, "debate.not_available")
    if pd.get("interpretation") in (None, "insufficient_data"):
        pd_value = na
    else:
        pd_value = t(lang, "debate.values.polarization",
                     initial=n(pd.get("initial_polarization", 0)), final=n(pd.get("final_polarization", 0)),
                     delta=fmt_signed(pd.get("delta", 0), 3, lang))
    if ec.get("score") is None:
        ec_value = na
    else:
        method = t(lang, "debate.methods." + ("embedding" if ec.get("method") == "embedding" else "jaccard"))
        ec_value = t(lang, "debate.values.echo", score=n(ec["score"]), method=method)
    if inf.get("interpretation") in (None, "insufficient_data"):
        inf_value = na
    else:
        inf_value = t(lang, "debate.values.diversity",
                      first=n(inf.get("first_half_keywords_avg", 0), 1),
                      second=n(inf.get("second_half_keywords_avg", 0), 1),
                      delta=fmt_signed(inf.get("delta_pct", 0), 1, lang))

    rows = [
        (t(lang, "debate.rows.polarization"), pd_value, _interp_label(pd.get("interpretation"), lang), pd),
        (t(lang, "debate.rows.echo"), ec_value, _interp_label(ec.get("interpretation"), lang), ec),
        (t(lang, "debate.rows.diversity"), inf_value, _interp_label(inf.get("interpretation"), lang), inf),
    ]
    table = [t(lang, "debate.table_header"), "|---|---|---|"]
    table += [f"| {name} | {value} | {label} |" for name, value, label, _ in rows]
    notes = [f"- **{name.split(' (')[0]}**: {_meaning(m.get('description', ''))}"
             for name, _, _, m in rows if m.get("description")]
    return "\n".join([debate_block_head(lang), "", *table, "", *notes])


_DEBATE_SUBHEADING = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
_METRIC_NAMES = (re.compile(r"polariz", re.I), re.compile(r"echo", re.I), re.compile(r"diversit", re.I))


def _debate_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Ogni sezione o sottosezione ('##' o '###') sulle dinamiche del dibattito, con la sua fine."""
    ranges = []
    for i, line in enumerate(lines):
        m = _DEBATE_SUBHEADING.match(line)
        if not (m and DEBATE_HEADING_RE.search(m.group(2))):
            continue
        level = len(m.group(1))
        end = len(lines)
        for j in range(i + 1, len(lines)):
            h = re.match(r"^(#{1,6})\s", lines[j])
            if h and len(h.group(1)) <= level:
                end = j
                break
        ranges.append((i, end))
    # Una sottosezione dentro una sezione gia' presa non conta due volte
    return [r for r in ranges if not any(o[0] < r[0] and r[1] <= o[1] for o in ranges)]


def _remove_metric_tables(lines: list[str]) -> tuple[list[str], int]:
    """Toglie le tabelle che riportano almeno due delle tre metriche del dibattito."""
    out, table, removed = [], [], 0

    def flush():
        nonlocal removed
        text = "\n".join(table)
        if table and sum(bool(p.search(text)) for p in _METRIC_NAMES) >= 2:
            removed += 1
        else:
            out.extend(table)
        table.clear()

    for line in lines:
        if line.strip().startswith("|"):
            table.append(line)
            continue
        flush()
        out.append(line)
    flush()
    return out, removed


def ensure_debate_section(md: str, block: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, dict]:
    """Esattamente una sezione "Dinamiche del Dibattito", prima degli scenari: la tabella del codice
    una volta, poi la lettura del modello. Le altre copie scritte dal modello (sezioni, sottosezioni,
    tabelle delle metriche) vengono tolte ovunque; il loro testo confluisce nella lettura.
    Ritorna (report, {"outcome", "model_sections", "tables_removed"})."""
    if not md:
        return md, {"outcome": "empty_report", "model_sections": 0, "tables_removed": 0}
    lines = md.replace(block, "").split("\n")
    ranges = _debate_ranges(lines)
    readings: list[str] = []
    for start, end in reversed(ranges):
        readings.insert(0, "\n".join(lines[start + 1:end]))
        del lines[start:end]
    lines, tables_removed = _remove_metric_tables(lines)

    block_heads = {debate_block_head(code) for code in SUPPORTED_LANGUAGES}
    paragraphs, seen = [], set()
    for chunk in readings:
        chunk_lines, n = _remove_metric_tables(chunk.split("\n"))
        tables_removed += n
        for para in re.split(r"\n\s*\n", "\n".join(chunk_lines)):
            key = _norm(para)
            if key and key not in seen and not any(head in para for head in block_heads):
                seen.add(key)
                paragraphs.append(para.strip("\n"))
    section = [f"## {debate_title(lang)}", "", block, ""] + ["\n\n".join(paragraphs), ""] * bool(paragraphs)

    if not ranges:
        outcome = "section_added"
    elif len(ranges) == 1:
        outcome = "block_inserted"
    else:
        outcome = "sections_merged"
    info = {"outcome": outcome, "model_sections": len(ranges), "tables_removed": tables_removed}
    for title_re in (SCENARIO_HEADING_RE, PREDICTION_HEADING_RE, CONFIDENCE_HEADING_RE, APPENDIX_HEADING_RE):
        anchor = section_bounds(lines, title_re)
        if anchor:
            lines[anchor[0]:anchor[0]] = section
            return _tidy("\n".join(lines)), info
    return _tidy("\n".join(lines).rstrip() + "\n\n" + "\n".join(section)), info



# ── Entropia: un solo valore ──────────────────────────────────────────────────

_ENTROPY_FIGURE = re.compile(
    r"(?i)(opinion[_ ]entropy|entropia(?:\s+delle\s+opinioni|\s+della\s+convinzione)?|\bentropy)([^\d\n]{0,25}?)(\d+[.,]\d+)")


_ROUND_SPECIFIC = re.compile(r"(?i)\b(?:al|nel|dal|per|ogni|in|at|by|each|every|from|after)\s+round\b|\bround\s+\d")
_LAST_ROUND = re.compile(r"(?i)\b(?:ultimo|last|final)\s+round\b")


def fix_entropy_values(md: str, entropy: float | None) -> tuple[str, int]:
    """Ogni opinion_entropy citata nel report diventa il valore del codice (ultimo round).

    Le frasi sui singoli round ("al round 2", "per round") restano: li' l'entropia e' un'altra.
    """
    if not md or entropy is None:
        return md, 0
    fixed = 0

    def repl(m):
        nonlocal fixed
        # "(ultimo round)" / "(last round)" e' l'etichetta del valore finale, non un round specifico
        between = re.sub(r"(?i)\(?\b(?:ultimo|last|final)\s+round\)?", "", m.group(2))
        if re.search(r"(?i)round|delta", between):
            return m.group(0)
        value = float(m.group(3).replace(",", "."))
        if abs(value - entropy) < 0.0006:
            return m.group(0)
        fixed += 1
        text = f"{entropy:.3f}"
        return m.group(1) + m.group(2) + (text.replace(".", ",") if "," in m.group(3) else text)

    out = []
    for line in md.split("\n"):
        sentences = _SENT_SPLIT.split(line)
        out.append(" ".join(
            s if re.search(r"(?i)\b(?:al|nel|dal|per|ogni|in|at|by|each|every|from|after)\s+round\b|\bround\s+\d",
                           re.sub(r"(?i)\b(?:ultimo|last|final)\s+round\b", "", s))
            else _ENTROPY_FIGURE.sub(repl, s)
            for s in sentences))
    return "\n".join(out), fixed


# ── Agenti adversarial: il testo segue i contatori ────────────────────────────

_NO_ADVERSARIAL = re.compile(
    r"(?i)\bnessun\w*\s+(?:agente\s+|agenti\s+)?(?:adversarial|avversari\w*)|"
    r"\bnon\s+(?:sono|è|e')\s+(?:stat[oi]\s+)?(?:presenti|present[ei]|inclus[oi]|inserit[oi])\s+"
    r"(?:agenti\s+)?(?:adversarial|avversari\w*)|"
    r"\b(?:agenti\s+)?(?:adversarial|avversari\w*)\s+non\s+(?:sono|è|e')\s+(?:stat[oi]\s+)?(?:presenti|inclus[oi]|inserit[oi])|"
    r"\bassenza\s+di\s+agenti\s+(?:adversarial|avversari\w*)|\b0\s+agenti\s+(?:adversarial|avversari\w*)|"
    r"\bno\s+adversarial\s+agents?\b|\bthere\s+(?:are|were)\s+no\s+adversarial|"
    r"\babsence\s+of\s+adversarial\s+agents?|\b(?:0|zero)\s+adversarial\s+agents?|"
    r"\badversarial\s+agents?\s+(?:were|was|are|is)\s+not\s+(?:present|included|added|used|injected)|"
    r"\bnone\s+of\s+the\s+agents\s+(?:were|was|are|is)\s+adversarial|"
    r"\b(?:did|does|do)\s+not\s+include\s+(?:any\s+)?adversarial\s+agents?")
_NAT_ONE = r"(?:(?:un|a|an)\s+)?(?:agente\s+naturale|natural\s+agent)"
_NAT_MANY = r"(?:agenti\s+naturali|natural\s+agents)"
_LIST_INTRO = (r"\s*,?\s*(?:come|quali|tra\s+cui|ad\s+esempio|includono|comprendono|"
               r"such\s+as|like|including|include|includes)\s+")
_PREDICATE = r"\s*(?:,|:|—|–|\s-\s|\bè\b|\be'|\bera\b|\bis\b|\bwas\b)\s*"


def _names_re(names: list[str]) -> str:
    return "(?<!\\w)(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + ")(?!\\w)"


def _inside_parens(text: str, pos: int) -> bool:
    return text.count("(", 0, pos) > text.count(")", 0, pos)


def _same_case(original: str, replacement: str) -> str:
    """La sostituzione prende la maiuscola iniziale del testo sostituito (inizio di frase)."""
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def _relabel_sentence(s: str, adv: list[str], natural: list[str], lang: str) -> tuple[str, int]:
    """Corregge "agente naturale" solo dove e' legato a un nome di agente adversarial:
    "<adv> (un agente naturale)", "<adv> e' un agente naturale", "l'agente naturale <adv>",
    "agenti naturali come <adv>, <adv>" (solo se tutti i nomi elencati sono adversarial). Un agente
    naturale non riceve mai l'etichetta, "voce critica" non viene toccata, niente parentesi annidate."""
    adv_re = _names_re(adv)
    nat_re = _names_re(natural) if natural else None
    n = 0

    def label(key, text, pos):
        flat = {"natural_one": "paren", "natural_many": "natural_many_flat"}[key]
        return t(lang, f"report.relabel.{flat if _inside_parens(text, pos) else key}")

    # 0. "<adv> ... is_adversarial: false" in the same clause, with no other agent in between
    #    (first: the relabels below add parentheses between the name and the flag)
    def flag(m):
        nonlocal n
        between = m.group(2)
        if re.search(adv_re, between) or (nat_re and re.search(nat_re, between)):
            return m.group(0)
        n += 1
        return f"{m.group(1)}{between}is_adversarial{m.group(3)}true"
    s = re.sub(rf"(?i)({adv_re})([^()\n.;]{{0,40}}?(?:\(\s*)?)is_adversarial(\s*(?:\*\*)?\s*[:=]\s*(?:\*\*)?\s*)false",
               flag, s)
    # 1. "<adv> (un agente naturale)" -> "<adv> (voce critica, agente adversarial)"
    s, k = re.subn(rf"(?i)({adv_re})(\s*)\(\s*{_NAT_ONE}\s*\)",
                   lambda m: f"{m.group(1)}{m.group(2)}({t(lang, 'report.relabel.paren')})", s)
    n += k
    # 2. "<adv> e' un agente naturale" / "<adv>, a natural agent"
    out, last = [], 0
    for m in re.finditer(rf"(?i)({adv_re})({_PREDICATE}){_NAT_ONE}\b", s):
        out.append(s[last:m.start()] + m.group(1) + m.group(2) + label("natural_one", s, m.start()))
        last, n = m.end(), n + 1
    s = "".join(out) + s[last:]
    # 3. "l'agente naturale <adv>" / "the natural agent <adv>"
    def before(m):
        key = "before_name_article" if m.group(1) else "before_name"
        return _same_case(m.group(0), f"{t(lang, f'report.relabel.{key}')} {m.group(2)}")
    s, k = re.subn(rf"(?i)(l'|the\s+)?\b(?:agente\s+naturale|natural\s+agent)\s+({adv_re})", before, s)
    n += k
    # 4. "agenti naturali come A e B": only if every agent named in the list is adversarial
    out, last = [], 0
    for m in re.finditer(rf"(?i)\b(?:(gli|i|the)\s+)?{_NAT_MANY}(?={_LIST_INTRO})", s):
        tail = re.split(r"[.;:)]", s[m.end():], maxsplit=1)[0]
        if re.search(adv_re, tail) and not (nat_re and re.search(nat_re, tail)):
            new = label("natural_many", s, m.start())
            if m.group(1):  # the article agrees with the label ("gli agenti" -> "le voci")
                new = f"{t(lang, 'report.relabel.many_article')} {new}"
            out.append(s[last:m.start()] + _same_case(m.group(0), new))
            last, n = m.end(), n + 1
    s = "".join(out) + s[last:]
    return s, n


def fix_adversarial_claims(md: str, adversarial_agents: int, names: list[str],
                           lang: str = DEFAULT_LANGUAGE,
                           natural_names: list[str] | None = None) -> tuple[str, dict]:
    """Con agenti adversarial nei contatori il report non puo' dire che non ce ne sono, ne' chiamare
    naturale una voce critica. Toglie le frasi "nessun agente adversarial" e corregge le etichette
    legate ai nomi delle voci critiche (names, dai contatori del run); i nomi degli agenti naturali
    (natural_names) non ricevono mai l'etichetta. Ritorna (report, {"removed", "relabelled"})."""
    info = {"removed": 0, "relabelled": 0}
    if not md or not adversarial_agents:
        return md, info
    names = [n for n in names if n and len(n) >= 6]
    # Un nome che e' anche di un agente naturale non identifica una voce critica
    natural = [n for n in (natural_names or []) if n and len(n) >= 3]
    names = [n for n in names if n.lower() not in {x.lower() for x in natural}]
    out, in_code = [], False
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            out.append(line)
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        kept = []
        for s in _SENT_SPLIT.split(body):
            if _NO_ADVERSARIAL.search(s):
                info["removed"] += 1
                continue
            if names and any(n.lower() in s.lower() for n in names):
                s, k = _relabel_sentence(s, names, natural, lang)
                info["relabelled"] += k
            kept.append(s)
        rest = " ".join(kept).strip()
        if rest.strip("*_ :"):
            out.append(prefix + rest)
    return _tidy("\n".join(out)), info


# ── opinion_strength e' convinzione, non approvazione ─────────────────────────

_STRENGTH_CONTEXT = re.compile(
    r"(?i)opinion[_ ]strength|convinzion|conviction|intensit|distribuzion|distribution|bucket|very_high|very_low|"
    r"\bhigh\b|very\s+high|molto\s+alt|fasce?\s+(?:alt|bass)")
_APPROVAL = re.compile(
    r"(?i)\bpositiv\w*|\bnegativ\w*|\bfavorevol\w*|\bsfavorevol\w*|\bapprov\w*|\bgradiment\w*|"
    r"\bapprezzament\w*|\bconsenso\s+(?:positivo|favorevole)|\bsupport\w*\s+(?:al|il|per)|\bapproval\b|"
    r"\b(?:un)?favou?rabl\w*|\bsupportive\b|\bin\s+favou?r\b|\bendors\w*")
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*%")


def strip_conviction_as_approval(md: str) -> tuple[str, int]:
    """Toglie le frasi che leggono le fasce di opinion_strength (convinzione) come approvazione,
    es. "distribuzione 100% positiva": un critico molto convinto sta nella fascia alta."""
    if not md:
        return md, 0
    removed = 0
    out, in_code = [], False
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            out.append(line)
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        sentences = _SENT_SPLIT.split(body)
        kept = [s for s in sentences
                if not (_STRENGTH_CONTEXT.search(s) and _APPROVAL.search(s) and _PERCENT.search(s))]
        removed += len(sentences) - len(kept)
        rest = " ".join(kept).strip()
        if len(kept) == len(sentences):
            out.append(line)
        elif rest.strip("*_ :"):
            out.append(prefix + rest)
    return _tidy("\n".join(out)) if removed else md, removed


# ── Riga dei limiti sulle raccomandazioni ─────────────────────────────────────

def _recommendation_heading_re() -> re.Pattern:
    from .sections import RECOMMENDATION_SECTIONS
    titles = {t(lang, f"report.sections.{name}") for lang in SUPPORTED_LANGUAGES for name in RECOMMENDATION_SECTIONS}
    alternatives = "|".join(re.escape(x) for x in sorted(titles, key=len, reverse=True))
    return re.compile(rf"(?i)raccomandazion|recommendation|{alternatives}")


def has_recommendations_section(md: str) -> bool:
    """Il report ha una sezione ('##' o '###') di raccomandazioni: titolo "Raccomandazioni" o una sezione
    dei template che le da' (sections.RECOMMENDATION_SECTIONS), in qualsiasi lingua del catalogo."""
    heading_re = _recommendation_heading_re()
    return any(re.match(r"^#{2,3}\s", line) and heading_re.search(line) for line in (md or "").split("\n"))


def drop_recommendations_limit(md: str) -> tuple[str, int]:
    """Senza una sezione di raccomandazioni, la riga dei limiti del metodo sulle raccomandazioni operative
    si toglie (nell'appendice, o ovunque se l'appendice manca). Ritorna (report, righe tolte)."""
    if not md or has_recommendations_section(md):
        return md, 0
    needles = {t(lang, "report.recommendations_needle").lower() for lang in SUPPORTED_LANGUAGES}
    lines = md.split("\n")
    bounds = section_bounds(lines, APPENDIX_HEADING_RE) or (0, len(lines))
    drop = {i for i in range(bounds[0], bounds[1])
            if not _ANY_HEADING.match(lines[i]) and any(n in lines[i].lower() for n in needles)}
    if not drop:
        return md, 0
    return _tidy("\n".join(line for i, line in enumerate(lines) if i not in drop)), len(drop)


# ── Quote della popolazione simulata: non sono pesi di mercato ────────────────
# Le percentuali dei segmenti le sceglie il Demographer e il numero di agenti lo sceglie l'utente: negli
# scenari e nella previsione non pesano un mercato. Le frasi restano, senza la cifra: "27% della popolazione
# simulata" si toglie, "2 su 17 agenti (11,8%)" diventa "pochi agenti". Nell'appendice restano.

_POP_NOUN = r"(?:(?:popolazione|campione)(?:\s+simulat[ao])?|(?:simulated\s+)?(?:population|sample))"
_AGENT_NOUN_IT = r"agenti(?:\s+naturali)?"
_AGENT_NOUN_EN = r"(?:natural\s+)?agents"
_NUM_VALUE = r"\d{1,3}(?:[.,]\d+)?"
# "27% della popolazione simulata", "che rappresenta il 27% della popolazione", "27% of the simulated population"
_POPULATION_PCT = re.compile(
    rf"(?i)(?:\s*[,;]\s*|\s+)?(?:\b(?:che\s+rappresent\w+|pari\s+al?|representing|which\s+(?:is|makes\s+up)|"
    rf"accounting\s+for)\s+)?(?:\b(?:il|lo|the|circa\s+il|about)\s+)?~?\s*{_NUM_VALUE}\s*%\s+"
    rf"(?:della|del|dello|of\s+the|of)\s+(?:{_POP_NOUN})")
# "2 su 17 agenti", "2 of 17 agents", "2 out of 17 natural agents", con l'eventuale "(11,8%)" che segue
_AGENT_COUNT = re.compile(
    rf"(?i)\b(\d{{1,4}})\s+(?:su|di|of|out\s+of)\s+(\d{{1,4}})(?:\s+({_AGENT_NOUN_IT}|{_AGENT_NOUN_EN}))?"
    rf"(\s*\(\s*~?{_NUM_VALUE}\s*%\s*\))?")
# "1 solo agente su 17", "only 1 agent out of 17", "3 agenti naturali su 15": il conteggio prima del nome
_AGENT_COUNT_NOUN_FIRST = re.compile(
    rf"(?i)\b(\d{{1,4}})\s+(?:sol[oaie]\s+)?(agent[ei](?:\s+natural[ei])?|(?:natural\s+)?agents?)\s+(?:su|di|of|out\s+of)\s+"
    rf"(?:(?:un\s+)?totale\s+di\s+|a\s+total\s+of\s+)?(\d{{1,4}})\b(\s*\(\s*~?{_NUM_VALUE}\s*%\s*\))?")
_SEGMENT_WORD = re.compile(r"(?i)segment|target|cluster|gruppo|group|quota|share|persona")


class _Reordered:
    """Un match con i gruppi (parte, totale, nome) in un altro ordine, per riusare la stessa sostituzione."""

    def __init__(self, m: re.Match, groups: tuple):
        self._m, self._g, self.string = m, groups, m.string

    def group(self, i: int = 0):
        return self._m.group(0) if i == 0 else self._g[i - 1]

    def start(self, *a):
        return self._m.start(*a)


def _share_bucket(ratio: float, largest: bool = False) -> str:
    """Il quantificatore della quota: sopra la meta' maggioranza; la posizione piu' numerosa sotto la meta' e'
    una maggioranza relativa, mai una minoranza."""
    if ratio <= 0:
        return "none"
    if ratio >= 1:
        return "all"
    if abs(ratio - 0.5) < 0.01:
        return "half"
    if ratio > 0.5:
        return "majority" if ratio < 0.8 else "almost_all"
    if largest:
        return "plurality"
    return "few" if ratio < 0.2 else "minority"


def _at_sentence_start(line: str, pos: int) -> bool:
    before = line[:pos].strip()
    return (not before or before[-1] in ".!?" or before.endswith("**:")
            or bool(re.fullmatch(r"[-*+>]|\d+[.)]|\*\*", before)))


def _agent_noun(noun: str | None, lang: str) -> str:
    """Il nome degli agenti nella lingua del report, "naturali" compreso se c'era."""
    natural = bool(noun and re.search(r"(?i)natural", noun))
    return t(lang, "report.population.noun_natural" if natural else "report.population.noun")


def remove_population_shares(md: str, *, total_agents: int, natural_agents: int, segments: list[dict] | None,
                             lang: str = DEFAULT_LANGUAGE, stance: dict | None = None) -> tuple[str, list[dict]]:
    """Negli scenari e nella previsione toglie le quote della popolazione simulata usate come peso di mercato:
    le percentuali di composizione del Demographer ("27% della popolazione simulata", "il segmento X (27%)")
    e i conteggi di agenti ("2 su 17 agenti"), che diventano un quantificatore scelto dalla quota reale.
    Restano le quote di posizione degli agenti naturali (calcolate dal codice): "il 46,7% degli agenti
    naturali", "7 su 15 agenti naturali" se 7 e' un conteggio di posizione. Ritorna (report, [{...}])."""
    if not md:
        return md, []
    totals = {n for n in (total_agents, natural_agents) if n}
    seg_pcts = set()
    for seg in segments or []:
        try:
            seg_pcts.add(round(float(seg.get("percentage")), 1))
        except (TypeError, ValueError, AttributeError):
            pass
    group_counts: dict[int, list[int]] = {}
    if stance_measured(stance):
        natural = list(stance["natural"]["final"]["counts"].values())
        everyone = [natural[k] + list(stance["adversarial"]["final"]["counts"].values())[k] for k in range(len(natural))]
        group_counts = {natural_agents: natural, total_agents: everyone}
    segment_pct = re.compile(
        rf"\s*\(\s*~?\s*({_NUM_VALUE})\s*%\s*\)|\s*,\s*(?:pari\s+al?|che\s+vale|representing|accounting\s+for)\s+"
        rf"~?\s*({_NUM_VALUE})\s*%(?=\s*(?:[,;.)]|$))", re.I)
    lines = md.split("\n")
    ranges = [(name, b) for name, b in (("scenarios", section_bounds(lines, SCENARIO_HEADING_RE)),
                                        ("prediction", section_bounds(lines, PREDICTION_HEADING_RE))) if b]
    found: list[dict] = []
    in_code = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        where = next((name for name, (start, end) in ranges if start < i < end), None)
        if in_code or where is None or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            continue
        removed: list[str] = []

        def count(m):
            part, whole = int(m.group(1)), int(m.group(2))
            if whole not in totals or part > whole:
                return m.group(0)
            counts = group_counts.get(whole) or []
            if m.group(3) and re.search(r"(?i)natural", m.group(3)) and part in counts:
                return m.group(0)  # a stance count of the natural agents, computed by the system
            largest = bool(counts) and part == max(counts) and counts.count(part) == 1
            removed.append(m.group(0).strip())
            text = t(lang, f"report.population.quantifiers.{_share_bucket(part / whole, largest)}",
                     noun=_agent_noun(m.group(3), lang))
            return _cased("A" if _at_sentence_start(m.string, m.start()) else m.group(0), text)

        def population(m):
            removed.append(m.group(0).strip(" ,;"))
            return ""

        def segment(m):
            raw = m.group(1) or m.group(2)
            if round(float(raw.replace(",", ".")), 1) not in seg_pcts:
                return m.group(0)
            removed.append(m.group(0).strip(" ,;()"))
            return ""

        new = _AGENT_COUNT.sub(count, line)
        new = _AGENT_COUNT_NOUN_FIRST.sub(
            lambda m: count(_Reordered(m, (m.group(1), m.group(3), m.group(2)))), new)
        new = _POPULATION_PCT.sub(population, new)
        if seg_pcts and _SEGMENT_WORD.search(new):
            new = segment_pct.sub(segment, new)
        if removed:
            found.append({"section": where, "removed": removed, "sentence": line.strip()[:200]})
            lines[i] = new
    if not found:
        return md, []
    return _tidy("\n".join(lines)), found


# ── Affermazioni degli agenti: non sono evidenze ──────────────────────────────
# Negli scenari e nella previsione un numero, una percentuale, un anno o un evento esterno con nome
# che non sta nel brief (ne' nei dati calcolati dal codice) e' un'affermazione di un agente: diventa
# "secondo <agente> (...)" e non vale come evidenza. Se nessun agente l'ha scritto, l'ha introdotto il
# modello: la frase si toglie.

_ANY_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?")
_PCT_CLAIM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d+)?)\s*(?:%|per\s*cento\b|percent\b)", re.I)
_YEAR_CLAIM = re.compile(r"(?<![\w.,])((?:19|20)\d\d)(?![\w]|[.,]\d)")
_MONEY_CLAIM = re.compile(
    r"(?:€|\$|£)\s*(\d+(?:[.,]\d+)*)|(?<![\w.,])(\d+(?:[.,]\d+)*)\s*(?:€|euro\b|dollar[ie]?\b|dollars\b|"
    r"milion[ie]\b|million\b|miliard[ie]\b|billion\b|mila\b|thousand\b|k\b)", re.I)
# Durate: affermazioni come le altre ("finestra di viralita' di 48-72 ore", "nei primi 30 giorni", "7 days"):
# un numero di giorni o di ore che non sta nel brief, nei dati ne' in un post e' inventato. "48-72 ore" conta entrambi.
_DURATION_UNITS = (r"(?:mesi|mese|anni|anno|settimane|settimana|giorni|giorno|ore|minuti|months?|years?|weeks?|days?|"
                   r"hours?|minutes?|h)\b")
_DURATION_CLAIM = re.compile(rf"(?<![\w.,])(\d{{1,3}})\s*{_DURATION_UNITS}", re.I)


def _duration_unit(text: str) -> str:
    """Unita' di una durata ("30 giorni" -> "day", "48-72 ore" -> "hour", "48h" -> "hour")."""
    words = re.sub(r"[\d.,–-]+", " ", text.lower()).split()
    for unit, stems in (("minute", ("minut",)), ("hour", ("ore", "ora", "hour", "h")), ("day", ("giorn", "day")),
                        ("week", ("settiman", "week")), ("month", ("mes", "month")), ("year", ("ann", "year"))):
        if any(w == s or (len(s) > 2 and w.startswith(s)) for w in words for s in stems):
            return unit
    return "other"
_DURATION_RANGE = re.compile(rf"(?<![\w.,])(\d{{1,3}})\s*[-–]\s*\d{{1,3}}\s*{_DURATION_UNITS}", re.I)
# Eta' ("consumatori di 25-45 anni", "aged 30", "20-year-olds"): non sono durate
_AGE = re.compile(r"(?i)(?:\b(?:di|tra|fra|tra\s+i|fra\s+i|sui|sotto\s+i|sopra\s+i|oltre\s+i|over|under|aged)\s+"
                  r"(?:\d{1,3}\s*[-–e]\s*)?$)")
_AGE_AFTER = re.compile(r"(?i)^[-\s]*(?:years?)?[-\s]*olds?\b")
_EVENT_CUE = re.compile(
    r"(?i)\b(?:pivot\w*|riposizionament\w*|repositioning|rebrand\w*|rilanc\w*|relaunch\w*|croll\w*|collaps\w*|"
    r"fallim\w*|bankrupt\w*|acquisizion\w*|acquisition\w*|acquired|merger|fusion\w*|scandal\w*|campagn\w*|"
    r"campaign\w*|lanci\w*|launch\w*|caso|case|crisi|crisis|boicott\w*|boycott\w*|richiam\w*|recall\w*)\b")
_PROPER_NAME = re.compile(r"(?<![\w'’])([A-ZÀ-Ý][a-zà-ÿ]{3,}(?:[-][A-ZÀ-Ý][a-zà-ÿ]+)?)(?:['’]s)?\b")
# Parole con la maiuscola che non sono nomi di aziende o eventi
_NOT_NAMES = {
    "the", "this", "these", "those", "there", "their", "they", "then", "than", "when", "while", "with", "without",
    "according", "after", "before", "only", "most", "some", "both", "each", "every", "other", "also", "however",
    "scenario", "scenarios", "prediction", "evidence", "agent", "agents", "natural", "critical", "stance",
    "reaction", "plausible", "reazione", "plausibile",
    "quest", "questo", "questa", "questi", "queste", "quello", "quella", "quando", "mentre", "secondo", "dopo",
    "prima", "solo", "anche", "ogni", "altri", "altre", "tutti", "tutte", "nessun", "nessuno", "scenari",
    "previsione", "evidenza", "agente", "agenti", "naturali", "voci", "critiche", "posizione", "infine",
    "inoltre", "tuttavia", "però", "quindi", "perché", "come", "dove", "senza", "verso", "contro", "presso",
}


# Anche prima di una frase che comincia con una cifra ("... bruschi. 35% dei negozi ...")
_CLAIM_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"«(*_]*[A-ZÀ-Ý0-9])")


def _numbers(text: str, pattern: re.Pattern = _ANY_NUMBER) -> set[float]:
    out = set()
    for m in pattern.finditer(text or ""):
        raw = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
        try:
            out.add(round(float(raw.replace(",", ".")), 3))
        except (TypeError, ValueError):
            pass
    return out


def _parse_amount(raw: str) -> float:
    """Importo con separatori delle migliaia o dei decimali: "1.500" e "1,500" -> 1500, "2,5" e "2.5" -> 2.5,
    "1.234,5" -> 1234.5, "1,234.5" -> 1234.5."""
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        raw = raw.replace(".", "").replace(",", "")
    else:
        raw = raw.replace(",", ".")
    return float(raw)


def _claim_tokens(sentence: str) -> list[tuple[str, str, float | None]]:
    """(kind, testo, valore) di percentuali, anni, importi e durate citati nella frase."""
    tokens = []
    for kind, pattern in (("percent", _PCT_CLAIM), ("year", _YEAR_CLAIM), ("money", _MONEY_CLAIM),
                          ("duration", _DURATION_CLAIM), ("duration", _DURATION_RANGE)):
        for m in pattern.finditer(sentence):
            if kind == "duration" and re.search(r"(?i)ann|year", m.group(0)) and (
                    _AGE.search(sentence[:m.start()]) or _AGE_AFTER.match(sentence[m.end():])):
                continue
            raw = next(g for g in m.groups() if g)
            try:
                value = round(_parse_amount(raw) if kind == "money" else float(raw.replace(",", ".")), 3)
            except ValueError:
                continue
            tokens.append((kind, m.group(0).strip(), value))
    # Un anno puo' essere anche un importo o una percentuale: una volta sola
    seen, unique = set(), []
    for kind, text, value in tokens:
        if (text, value) not in seen:
            seen.add((text, value))
            unique.append((kind, text, value))
    return unique


# Nomi di aziende, marchi, prodotti o eventi esterni: una parola con la maiuscola a meta' frase accanto a un
# richiamo aziendale (competitor, brand, slogan, "come X", "such as X"...) o in un elenco di nomi, e gli slogan tra
# virgolette in maiuscole ("Just Do It"). Non sono nomi: le parole del catalogo, gli agenti, mesi, giorni, paesi,
# generazioni e le piattaforme social (sono canali, non terze parti del caso).
_ENTITY_CUE = re.compile(
    r"(?i)\b(?:competitor\w*|concorrent\w*|rival\w*|brand\w*|marc(?:a|he)\b|marchi\w*|aziend\w*|compan(?:y|ies)|"
    r"slogan\w*|payoff|player\w*|label\w*|catena|catene|chains?|retailer\w*|come|such\s+as|like|ad\s+es\w*|e\.g)\b")
_GENERIC_PROPER = {
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
    "novembre", "dicembre", "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "italia", "italy", "italiano",
    "italiana", "italiani", "italiane", "italian", "italians", "europa", "europe", "european", "europeo", "europea",
    "europei", "america", "american", "americans", "millennials", "millennial", "boomer", "boomers", "zoomer",
    "instagram", "tiktok", "facebook", "linkedin", "youtube", "reddit", "whatsapp", "twitter", "telegram", "threads",
    "google", "web", "internet", "report", "scenario", "scenari",
}
_MID_CAPITAL = re.compile(r"(?<=[a-zà-ÿ0-9,;] )([A-ZÀ-Ý][a-zà-ÿ][\w'’-]*)")
_QUOTED_TITLE = re.compile(r"[\"“«]([A-ZÀ-Ý][^\"”»\n]{2,60})[\"”»]")


@functools.lru_cache(maxsize=1)
def _catalog_words() -> frozenset:
    """Le parole dei testi del report nel catalogo (titoli, etichette, frasi del codice) in tutte le lingue."""
    words: set[str] = set()

    def walk(v):
        if isinstance(v, str):
            words.update(w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]+", v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for lang in SUPPORTED_LANGUAGES:
        for key in ("report", "debate", "confidence"):
            try:
                walk(t_value(lang, key))
            except KeyError:
                pass
    return frozenset(words)


def _in_texts(name: str, agent_texts: list[tuple[str, str]]) -> bool:
    pattern = re.compile(rf"(?i)(?<![\w]){re.escape(name)}(?![\w])")
    return any(pattern.search(text) for _, text in agent_texts)


def _entity_names(sentence: str, known_text: str, agent_texts: list[tuple[str, str]],
                  skip: set[str], common: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(nomi scritti da un agente accanto a un evento, nomi che nessuno ha scritto). Un nome del brief o dei dati
    non conta; uno scritto in un post senza un evento e' solo citato."""
    m = re.match(r"^\s*(\*\*[^*\n]{1,60}\*\*\s*:?\s*)?[\"«“(*_]*", sentence)
    start = m.end() if m else 0
    candidates = []
    for nm in _PROPER_NAME.finditer(sentence):
        name, low = nm.group(1), nm.group(1).lower()
        if (nm.start() <= start or _clause_start(sentence, nm.start()) or low in _NOT_NAMES or low in skip
                or low in _GENERIC_PROPER or low in _COMMON_WORDS or low in common):
            continue
        if low in known_text or low in _catalog_words():
            continue
        candidates.append(name)
    candidates = list(dict.fromkeys(candidates))
    posted = [n for n in candidates if _in_texts(n, agent_texts)]
    unknown = [n for n in candidates if n not in posted]
    invented = unknown if unknown and (_ENTITY_CUE.search(sentence) or _EVENT_CUE.search(sentence)
                                        or len(unknown) >= 2) else []
    for q in _QUOTED_TITLE.finditer(sentence):
        inner = q.group(1).strip()
        caps = re.findall(r"(?<![\w])[A-ZÀ-Ý][\w'’-]*", inner)
        if len(caps) >= 2 and inner.lower() not in known_text and not _in_texts(inner, agent_texts):
            invented.append(inner)
    posted = posted if _EVENT_CUE.search(sentence) else []
    return posted, list(dict.fromkeys(invented))



# Parole comuni che a inizio frase o citazione hanno la maiuscola ma non sono nomi
_COMMON_WORDS = {
    "finalmente", "purtroppo", "ovviamente", "sicuramente", "certamente", "infatti", "comunque", "inoltre",
    "tuttavia", "quindi", "allora", "ancora", "oggi", "ieri", "domani", "certo", "forse", "davvero", "proprio",
    "ecco", "bene", "male", "grazie", "peccato", "basta", "attenzione", "nota", "sinceramente", "onestamente",
    "personalmente", "secondo", "speriamo", "spero", "credo", "penso", "vedremo", "aspetto", "aspettiamo",
    "interessante", "bello", "bella", "bravi", "complimenti", "insomma", "anzi", "magari", "perfetto", "esatto",
    "finally", "unfortunately", "obviously", "surely", "certainly", "indeed", "anyway", "however", "honestly",
    "actually", "really", "today", "tomorrow", "yesterday", "maybe", "perhaps", "sure", "thanks", "note", "well",
    "great", "nice", "personally", "frankly", "hopefully", "interesting", "exactly", "perfect", "still",
}
_CLAUSE_OPENERS = "(:;\"“«'—–[-"


def _clause_start(sentence: str, pos: int) -> bool:
    """La parola a pos apre la frase, una clausola, una voce di elenco o una citazione."""
    before = sentence[:pos].rstrip(" \t*_")
    return not before or before[-1] in _CLAUSE_OPENERS or before[-1] in ".!?"


_QUOTE_SPAN = re.compile(r"\"([^\"\n]{6,})\"|“([^”\n]{6,})”|«([^»\n]{6,})»")


def _norm_quote(text: str) -> str:
    text = re.sub(r"(\.\.\.|…)", " ", text.lower().replace("’", "'"))
    return re.sub(r"[^\w']+", " ", text).strip()


def _quote_of(quote: str, texts: list[str]) -> bool:
    """La citazione riprende (anche troncata o con piccole differenze) uno dei testi."""
    q = _norm_quote(quote)
    if len(q) < 6:
        return False
    import difflib
    for text in texts:
        p = _norm_quote(text)
        if q in p:
            return True
        # Quasi contigua: una citazione troncata o con un ritocco, non lettere sparse in un post lungo
        block = difflib.SequenceMatcher(None, q, p, autojunk=False).find_longest_match(0, len(q), 0, len(p))
        if block.size >= 0.8 * len(q):
            return True
    return False


def mask_post_quotes(sentence: str, agent_texts: list[tuple[str, str]]) -> str:
    """Le citazioni tra virgolette che riprendono un post (o il profilo) dell'agente nominato nella frase, o di un
    agente qualsiasi se la frase non ne nomina, diventano spazi: sono citazioni, non affermazioni."""
    named = [a for a in {a for a, _ in agent_texts} if a in sentence]
    texts = [x for a, x in agent_texts if not named or a in named]

    def mask(m):
        inner = next(g for g in m.groups() if g is not None)
        # Senza un agente nominato serve un estratto vero, non tre parole ("Just Do It" in un post qualsiasi)
        if not named and len(_norm_quote(inner)) < 25:
            return m.group(0)
        return " " * len(m.group(0)) if _quote_of(inner, texts) else m.group(0)

    return _QUOTE_SPAN.sub(mask, sentence)


def _split_clauses(sentence: str) -> list[tuple[str, str]]:
    """[(separatore prima, clausola)], separando su , e ; fuori da parentesi e virgolette."""
    parts, buf, sep, depth, quote = [], "", "", 0, None
    closing = {'"': '"', "“": "”", "«": "»"}
    for ch in sentence:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
            continue
        if ch in closing:
            quote = closing[ch]
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",;":
            parts.append((sep, buf))
            sep, buf = ch, ""
            continue
        buf += ch
    parts.append((sep, buf))
    return parts


def drop_claim_fragments(sentence: str, items: list[str], names: list[str]) -> str:
    """Toglie dalla frase le clausole con un'affermazione non verificata, tenendo quelle che nominano un agente
    ("Mario Rossi (buyer), che cita il crollo di X nel 2012, resta contrario" -> "Mario Rossi (buyer) resta
    contrario"). In una clausola che nomina un agente si toglie solo l'elemento."""
    parts = _split_clauses(sentence)
    end = re.search(r"[.!?]+\s*$", sentence)
    out, dropped_sep = "", None
    for sep, clause in parts:
        has_item = any(item and item in clause for item in items)
        has_name = any(n in clause for n in names)
        if has_item and not has_name:
            dropped_sep = sep if dropped_sep is None else dropped_sep
            continue
        if has_item:
            for item in items:
                clause = clause.replace(item, "")
            clause = re.sub(r"[ \t]{2,}", " ", clause)
        if not out:
            out = clause.strip()
        elif dropped_sep == "," and sep == "," and clause.strip()[:1].islower():
            out += clause  # la clausola tolta stava tra due virgole: la frase principale continua
        else:
            out += sep + clause
        dropped_sep = None
    out = out.strip().rstrip(",;: ")
    if end and not re.search(r"[.!?]$", out):
        out += end.group(0).strip()
    return out


_ABBREVIATION_END = re.compile(
    r"(?i)(?:^|[\s(])(?:e\.g|i\.e|es|ad\s+es|ecc|etc|vs|cfr|ca|approx|nr|fig|mr|mrs|ms|dr|sig|dott|prof)\.$")


def claim_sentences(body: str) -> list[str]:
    """Le frasi di una riga; dopo un'abbreviazione ("e.g.", "ad es.") la frase continua."""
    out: list[str] = []
    for part in _CLAIM_SENT_SPLIT.split(body):
        if out and _ABBREVIATION_END.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _source_agent(tokens: list[tuple[str, str, float | None]], names: list[str],
                  agent_numbers: list[set[float]], agent_texts: list[tuple[str, str]]) -> str | None:
    """L'autore del testo (post, poi profilo) che contiene piu' affermazioni della frase; a pari merito il
    primo nel feed, cioe' chi l'ha detto per primo."""
    best, best_hits = None, 0
    for (agent, text), numbers in zip(agent_texts, agent_numbers):
        hits = sum(1 for _, _, v in tokens if v in numbers)
        hits += sum(1 for n in names if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", text))
        if hits > best_hits:
            best, best_hits = agent, hits
    return best


def _keep_capital(word: str, proper: set[str]) -> bool:
    """La maiuscola resta su una sigla o su un nome proprio (scritto con la maiuscola a meta' frase nelle fonti e
    mai in minuscolo: "Il", "Gli", "The" no)."""
    return (word.isupper() and len(word) > 1) or word.lower() in proper


# La frase attribuisce gia' l'affermazione agli agenti, anche senza nome ("un agente racconta che...",
# "ricordano alcuni agenti", "one agent recalls", "some agents point to"): resta com'e'
_AGENT_SUBJECT = r"(?:un|uno|un'|l'|gli|alcuni|diversi|molti|vari|pochi|one|an|some|several|many|a\s+few|the|two|three)\s+agent[ie]?s?"
_REPORT_VERB = (r"(?:raccont\w*|ricord\w*|dic\w*|dice|dicono|affer\w*|sostien\w*|cit\w*|scriv\w*|riferisc\w*|osserv\w*|"
                r"segnal\w*|not\w*|menzion\w*|richiam\w*|recall\w*|say\w*|said|claim\w*|argu\w*|cite\w*|writ\w*|wrote|"
                r"note\w*|mention\w*|report\w*|point\w*|warn\w*|avvert\w*)")
_GENERIC_ATTRIBUTION = re.compile(
    rf"(?i)\b{_AGENT_SUBJECT}\b(?:\s+\w+){{0,3}}?\s+{_REPORT_VERB}\b|\b{_REPORT_VERB}\s+(?:\w+\s+){{0,2}}{_AGENT_SUBJECT}\b|"
    rf"\b(?:secondo|according\s+to)\s+{_AGENT_SUBJECT}\b")


def _with_attribution(sentence: str, agent: str, lang: str, proper: set[str] | None = None) -> str:
    """"Secondo <agente>, <frase> (affermazione dell'agente, ...)." in testa alla frase intera, dopo un'eventuale
    etichetta in grassetto: mai in mezzo alla frase."""
    m = re.match(r"^(\*\*[^*\n]{1,60}\*\*\s*:?\s*)(.*)$", sentence)
    label, rest = (m.group(1), m.group(2)) if m else ("", sentence)
    rest = rest.strip()
    end_m = re.search(r"([.!?…]+)\s*$", rest)
    end = "."
    if end_m:
        end = "?" if "?" in end_m.group(1) else "!" if "!" in end_m.group(1) else "."
        rest = rest[:end_m.start()].rstrip()
    w = re.match(r"([\"«“(*_]*)([A-ZÀ-Ý][\w'’-]*)", rest)
    if w and not _keep_capital(w.group(2), proper or set()):
        rest = w.group(1) + w.group(2)[:1].lower() + rest[len(w.group(1)) + 1:]
    return label + t(lang, "report.claims.attributed", agent=agent, sentence=rest, end=end)


# Sezioni scritte dal codice o copiate dal catalogo: il controllo delle affermazioni non le tocca
_NOT_ANALYSIS = (SIM_METRICS_HEADING_RE, DEBATE_HEADING_RE, CONFIDENCE_HEADING_RE, APPENDIX_HEADING_RE)


def analysis_sections(lines: list[str]) -> list[tuple[str, tuple[int, int]]]:
    """Le sezioni '## ' di analisi scritte dal modello: tutte, comprese quelle dei template, tranne metriche,
    dinamiche del dibattito, confidenza e appendice. Nome: "scenarios", "prediction" o il titolo."""
    out = []
    for i, line in enumerate(lines):
        m = _TOP_HEADING.match(line)
        if not m or len(m.group(1)) != 2:
            continue
        title = m.group(2).strip("*_ ")
        if any(r.search(title) for r in _NOT_ANALYSIS):
            continue
        end = next((j for j in range(i + 1, len(lines)) if _TOP_HEADING.match(lines[j])), len(lines))
        name = ("scenarios" if SCENARIO_HEADING_RE.search(title)
                else "prediction" if PREDICTION_HEADING_RE.search(title) else title)
        out.append((name, (i, end)))
    return out


def mark_unverified_claims(md: str, *, brief: str, allowed_texts: list[str], agent_texts: list[tuple[str, str]],
                           lang: str = DEFAULT_LANGUAGE, computed: set[float] | None = None,
                           agent_roles: list[str] | None = None) -> tuple[str, list[dict]]:
    """In ogni sezione di analisi (analysis_sections) le affermazioni che non stanno nel brief ne' nei dati del
    codice: numeri, percentuali, anni, importi, durate e nomi di aziende, marchi, prodotti o eventi esterni.
    - scritte da un agente (post o profilo): la frase resta, attribuita ("Secondo <agente>, ..."); se la frase
      nomina gia' quell'agente resta com'e'. Un nome scritto da un agente senza un evento (pivot, lancio,
      crisi...) e' solo citato e resta;
    - non scritte da nessuno: le ha introdotte il modello, la frase si toglie; se la frase nomina un agente si
      toglie solo la clausola con l'affermazione (drop_claim_fragments).
    Non sono affermazioni: le citazioni tra virgolette di un post dell'agente nominato (mask_post_quotes); come nomi,
    le parole che aprono una frase, una clausola o una citazione, le parole dei ruoli e dei nomi degli agenti, le
    parole comuni (scritte in minuscolo nelle fonti o nel report, o in _COMMON_WORDS).
    allowed_texts: topic, requisito, scheda soggetto/popolazione, tabelle e frasi del codice.
    agent_texts: (agente, testo) in ordine: i post del feed, poi i profili.
    computed: ogni numero calcolato dal sistema e dato al report (SimulationToolExecutor.computed_numbers): non e'
    mai un'affermazione, in qualsiasi forma, con una tolleranza di arrotondamento.
    Una percentuale e' verificata solo se il brief o i dati la riportano come percentuale (i numeri di pagina
    e di nota del brief non valgono); anni, importi e durate se il numero compare.
    Ritorna (report, [{"section", "claims", "source", "action", "sentence"}]); action: attributed,
    attributed_in_text, removed."""
    if not md or not (brief or "").strip():
        return md, []
    known = " ".join([brief, *allowed_texts])
    known_text = known.lower()
    allowed = {"percent": _numbers(known, _PCT_CLAIM), "other": _numbers(known)}
    # Una durata e' verificata solo come durata della stessa unita' ("30 giorni" non diventa vero perche' gli
    # agenti sono 30 o perche' il brief parla di persone di 20-30 anni)
    durations = {(v, _duration_unit(text)) for kind, text, v in _claim_tokens(known) if kind == "duration"}
    computed_values = sorted(computed or ())
    agent_texts = [(a, x) for a, x in agent_texts if a and x]
    agent_numbers = [_numbers(x) for _, x in agent_texts]
    skip = {part.lower() for a, _ in agent_texts for part in re.split(r"[\s'’-]+", a) if part}
    skip |= {w.lower() for role in agent_roles or [] for w in re.findall(r"[\wÀ-ÿ'’-]+", role or "")}
    names = sorted({a for a, _ in agent_texts}, key=len, reverse=True)
    sources = [known, *(x for _, x in agent_texts)]
    lowercase = {w for text in sources for w in re.findall(r"(?<![\w'’])[a-zà-ÿ][\w'’-]*", text)}
    common = lowercase | set(re.findall(r"(?<![\w'’])[a-zà-ÿ][\w'’-]*", md))
    proper = {w.lower() for text in sources for w in _MID_CAPITAL.findall(text) if w.lower() not in lowercase} | skip
    lines = md.split("\n")
    ranges = analysis_sections(lines)
    found: list[dict] = []
    drop: set[int] = set()
    in_code = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        where = next((name for name, (start, end) in ranges if start < i < end), None)
        if in_code or where is None or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        sentences, changed = [], False
        for s in claim_sentences(body):
            plain = mask_post_quotes(s, agent_texts)
            tokens = [tok for tok in _claim_tokens(plain)
                      if ((tok[2], _duration_unit(tok[1])) not in durations if tok[0] == "duration" else
                          tok[2] not in allowed["percent" if tok[0] == "percent" else "other"]
                          and not any(abs(tok[2] - v) <= 0.05 for v in computed_values))]
            posted, invented = _entity_names(plain, known_text, agent_texts, skip, common)
            if not tokens and not posted and not invented:
                sentences.append(s)
                continue
            claims = [text for _, text, _ in tokens] + posted + invented
            source = None if invented else _source_agent(tokens, posted, agent_numbers, agent_texts)
            if source and (re.search(rf"(?i)(?<![\w]){re.escape(source)}(?![\w])", s) or _GENERIC_ATTRIBUTION.search(s)):
                found.append({"section": where, "claims": claims, "source": source, "action": "attributed_in_text",
                              "sentence": s[:200]})
                sentences.append(s)
                continue
            lead = re.match(r"^\s*(?:\*\*[^*\n]{1,60}\*\*\s*:?\s*)?[\"«“(*_]*", s).end()
            named = [n for n in names if s.startswith(n, lead)]
            if not source and named:
                # La frase presenta un agente (il suo nome la apre, spesso citato dopo): resta, senza la clausola
                # non verificata. Se l'agente e' solo nominato a meta' frase la frase si toglie come le altre
                kept = drop_claim_fragments(s, claims, named)
                found.append({"section": where, "claims": claims, "source": None, "action": "fragment_removed",
                              "sentence": s[:200]})
                changed = True
                if kept.strip("*_ :.,;"):
                    sentences.append(kept)
                continue
            found.append({"section": where, "claims": claims, "source": source,
                          "action": "attributed" if source else "removed", "sentence": s[:200]})
            changed = True
            if source:
                sentences.append(_with_attribution(s, source, lang, proper))
        if changed:
            rest = " ".join(sentences).strip()
            if rest.strip("*_ :"):
                lines[i] = prefix + rest
            else:
                drop.add(i)
    if not any(f["action"] != "attributed_in_text" for f in found):
        return md, found
    return _tidy("\n".join(line for i, line in enumerate(lines) if i not in drop)), found


# ── Ruoli degli agenti: quelli della persona ──────────────────────────────────
# "Giuseppe Bianchi, buyer di una catena..." quando Giuseppe Bianchi e' un coordinatore del benessere aziendale: il
# ruolo scritto accanto al nome (tra parentesi o dopo la virgola) che richiama il ruolo di un ALTRO agente e
# nessuna parola del proprio diventa il ruolo della persona.

_ROLE_GENERIC = {"agente", "agenti", "agent", "agents", "persona", "utente", "utenti", "user", "users", "della",
                 "delle", "degli", "dello", "nella", "nelle", "with", "from", "that", "their", "sono", "anni", "years",
                 "naturale", "natural", "critica", "critical", "voce", "voice"}


def _role_words(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-zà-ÿ]+", (text or "").lower()) if len(w) >= 4 and w not in _ROLE_GENERIC}


def _role_text(role: str) -> str:
    first = role.split(" ", 1)[0]
    return role if first.isupper() and len(first) > 1 else role[:1].lower() + role[1:]


def fix_agent_roles(md: str, roles: dict[str, str] | None, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """Il ruolo scritto accanto al nome di un agente ("Nome (ruolo)", "Nome, ruolo,") deve essere quello della sua
    persona. Ritorna (report, [{"agent", "written", "persona_role"}])."""
    roles = {n: r for n, r in (roles or {}).items() if n and r and len(n) >= 4}
    if not md or not roles:
        return md, []
    words = {n: _role_words(r) for n, r in roles.items()}
    every = set().union(*words.values())
    found: list[dict] = []

    def wrong(name: str, written: str) -> bool:
        w = _role_words(written)
        return bool(w & (every - words[name])) and not (w & words[name])

    lines, in_code = md.split("\n"), False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            continue
        new = line
        for name in sorted(roles, key=len, reverse=True):
            if name not in new:
                continue
            esc = re.escape(name)

            def paren(m, name=name):
                if not wrong(name, m.group(1)):
                    return m.group(0)
                found.append({"agent": name, "written": m.group(1).strip(), "persona_role": roles[name]})
                return f"{name} ({_role_text(roles[name])})"

            def apposition(m, name=name):
                if not wrong(name, m.group(2)):
                    return m.group(0)
                found.append({"agent": name, "written": m.group(2).strip(), "persona_role": roles[name]})
                role = _role_text(roles[name])
                if m.group(1) and m.group(1).lower() in ("a", "an", "the") and lang == "en":
                    article = "an" if role[:1].lower() in "aeiou" else "a"
                    return f"{name}, {article} {role}"
                return f"{name}, {role}"

            new = re.sub(rf"(?<![\w]){esc}\s*\(([^()\n]{{3,80}})\)", paren, new)
            new = re.sub(rf"(?<![\w]){esc},\s+(?:(un|una|uno|il|la|lo|a|an|the)\s+|l')?([^,.;:()\n]{{3,80}}?)(?=\s*[,;:.])",
                         apposition, new)
        lines[i] = new
    return ("\n".join(lines), found) if found else (md, [])


# ── "Piu' plausibile" solo quando le evidenze separano gli scenari ────────────
# Con confidenza bassa (o indicativa) e consenso sulla posizione non alto, o con la posizione non misurata,
# nessuno scenario e' "piu' plausibile": l'etichetta diventa "plausibile" e la sezione chiude con la nota.

def most_plausible_allowed(conf: dict | None, stance: dict | None) -> bool:
    level = stance_consensus_level(stance)
    if level is None:
        return False
    return not (conf and conf.get("level") == "bassa" and level != "high")


def enforce_scenario_likelihood(md: str, conf: dict | None, stance: dict | None,
                                lang: str = DEFAULT_LANGUAGE) -> tuple[str, dict]:
    """Toglie "piu' plausibile" dagli scenari quando most_plausible_allowed e' falso (le frasi negate, cioe' la
    nota di chiusura, restano) e aggiunge la nota se manca. Ritorna (report, {"relabelled", "note_added"})."""
    info = {"relabelled": 0, "note_added": False}
    if not md or most_plausible_allowed(conf, stance):
        return md, info
    lines = md.split("\n")
    bounds = section_bounds(lines, SCENARIO_HEADING_RE)
    if not bounds:
        return md, info
    most = t(lang, "report.likelihood.most")
    plausible = t(lang, "report.likelihood.plausible")
    variants = sorted({most, most.replace("ù", "u'"), "più plausibile", "most plausible"}, key=len, reverse=True)
    label = "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in variants)
    with_article = re.compile(rf"(?i)\b(?:il|lo|the)\s+(?:{label})(?=\s*(?:[.,;:!?)]|$|\(|perch|because|since|poich))")
    bare = re.compile(rf"(?i)\b(?:{label})\b")
    has_note = False
    for i in range(bounds[0] + 1, bounds[1]):
        line = lines[i]
        if not line.strip() or line.strip().startswith("|") or not bare.search(line):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        parts = []
        for s in _CLAIM_SENT_SPLIT.split(body):
            if bare.search(s) and _NEGATION.search(s) and not _ANY_HEADING.match(line):
                has_note = True
                parts.append(s)
                continue
            s, n1 = with_article.subn(lambda m: _cased(m.group(0), plausible), s)
            s, n2 = bare.subn(lambda m: _cased(m.group(0), plausible), s)
            info["relabelled"] += n1 + n2
            parts.append(s)
        lines[i] = prefix + " ".join(parts)
    if not has_note:
        last = max((j for j in range(bounds[0] + 1, bounds[1]) if lines[j].strip()), default=bounds[0])
        lines[last + 1:last + 1] = ["", t(lang, "report.likelihood.no_most_note")]
        info["note_added"] = True
    return _tidy("\n".join(lines)), info


# ── "Maggioranza" solo sopra il 50% ───────────────────────────────────────────

_MAJORITY_WORD = re.compile(r"(?i)\b(maggioranz[ae])(\s+(?:assolut[ae]|relativ[ae]))?\b|\b(majority)\b")
# "non raggiunge la maggioranza", "resta sotto la maggioranza", "short of a majority": la frase dice gia' che
# non c'e' maggioranza, riscriverla la contraddirebbe
_COMPARATIVE = re.compile(
    r"(?i)\b(?:raggiung\w*|reach\w*|sotto|sopra|oltre|meno|più|piu'?|below|above|under|over|less|more|than|"
    r"short\s+of|close\s+to|vicin\w*|quasi|almost|nearly|supera\w*|exceed\w*|manca\w*|lack\w*|lontan\w*|far\s+from)\b")
_MAJORITY_NEG = re.compile(r"(?i)\b(?:nessuna|senza|non\s+c'è|no|without|not\s+a)\s+$")


def fix_false_majority(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """"Maggioranza"/"majority" accanto a una quota del 50% o meno (la posizione piu' frequente, non la meta' piu'
    uno): "maggioranza relativa" / "plurality". Tabelle, titoli e codice restano. Ritorna (report, [...])."""
    if not md:
        return md, []
    lines, found, in_code = md.split("\n"), [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line) or not _MAJORITY_WORD.search(line):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        parts = []
        for s in _CLAIM_SENT_SPLIT.split(body):
            pcts = [(m.start(), float(m.group(1).replace(",", "."))) for m in _PCT_CLAIM.finditer(s)]

            def repl(m, s=s, pcts=pcts):
                clause = re.split(r"[,;:]", s[:m.start()])[-1]
                if (_MAJORITY_NEG.search(s[:m.start()]) or _NEGATION.search(clause) or _COMPARATIVE.search(clause)
                        or (m.group(2) and m.group(2).strip())
                        or re.match(r"(?i)\s*(?:assolut|absolut)", s[m.end():])):
                    return m.group(0)
                near = sorted((abs(p - m.start()), v) for p, v in pcts if abs(p - m.start()) <= 60)
                if not near or near[0][1] > 50:
                    return m.group(0)
                found.append({"sentence": s[:200], "share_pct": near[0][1]})
                if m.group(3):
                    return _cased(m.group(3), "plurality")
                return _cased(m.group(1), m.group(1)) + " relativa" if m.group(1).lower().endswith("a") else \
                    _cased(m.group(1), m.group(1)) + " relative"

            parts.append(_MAJORITY_WORD.sub(repl, s))
        lines[i] = prefix + " ".join(parts)
    return ("\n".join(lines), found) if found else (md, [])


# ── "Consenso" e' solo l'accordo sulla posizione ──────────────────────────────

_CONSENSUS_WORD = re.compile(r"(?i)\bconsens[oi]\b|\bconsensus\b")
_CONVICTION_CONTEXT = re.compile(r"(?i)convinzion|conviction|opinion[_ ]strength|varianz|variance|omogeneit|uniformit")
_STANCE_CONTEXT = re.compile(
    r"(?i)posizion|\bstance|a\s+favore|sostegn|\bsupport|contrari|\boppos|favorevol|\bagainst\b|in\s+favou?r")
_CONS_LEVEL = (r"molto\s+alt[oa]|alt[oa]|elevat[oa]|fort[ei]|ampi[oa]|medi[oa]|moderat[oa]|bass[oa]|debole|scars[oa]|"
               r"very\s+high|high|strong|broad|wide|medium|moderate|low|weak|limited")
_CONS_THEN_LEVEL = re.compile(
    rf"(?i)\b(livello\s+di\s+consenso|consenso|consensus(?:\s+level)?|level\s+of\s+consensus)"
    rf"((?:\*\*)?\s*(?::|=|\bè\b|\be'|\bera\b|\brisulta\b|\bis\b|\bwas\b|\bremains\b)?\s*(?:\*\*)?\s*)"
    rf"({_CONS_LEVEL})\b")
_LEVEL_THEN_CONS = re.compile(
    r"(?i)\b(molto\s+alt[oa]|alt[oa]|elevat[oa]|fort[ei]|ampi[oa]|medi[oa]|moderat[oa]|bass[oa]|debole|scars[oa]|"
    r"very\s+high|high|strong|broad|wide|medium|moderate|low|weak|limited)(\s+)(consenso|consensus)\b")
_IT_ARTICLES = r"il|lo|un|del|al|sul|nel|dal"
# Disclosure on the critical voices ("added to stress-test the consensus"): reworded, not removed
_DISCLOSURE_CONTEXT = re.compile(r"(?i)advers|avversar|voc[ei]\s+critic|critical\s+voice|stress")
_LEVEL_PHRASE = re.compile(rf"(?i)(?:{_CONS_THEN_LEVEL.pattern[4:]})|(?:{_LEVEL_THEN_CONS.pattern[4:]})")


def _cons_level_of(word: str) -> str:
    w = re.sub(r"\s+", " ", word.lower())
    if w.startswith(("bass", "debol", "scars", "low", "weak", "limited")):
        return "low"
    if w.startswith(("medi", "moderat", "medium", "moderate")):
        return "medium"
    return "high"


def _cased(original: str, text: str) -> str:
    return text[:1].upper() + text[1:] if original[:1].isupper() else text


def _cased_at(s: str, start: int, original: str, text: str) -> str:
    """Maiuscola solo a inizio frase; altrove la minuscola, salvo una sigla tutta maiuscola."""
    if not s[:start].strip(" *_\"«(“'"):
        return text[:1].upper() + text[1:]
    if len(original) > 1 and original.isupper():
        return text
    return text[:1].lower() + text[1:]


def _replace_noun(s: str, noun: str, articles: dict) -> str:
    """Ogni "consenso" restante diventa noun; l'articolo italiano davanti si accorda ("il consenso" ->
    "l'omogeneita' della convinzione", "le posizioni prevalenti")."""
    s = _CONSENSUS_WORD.sub(lambda m: _cased_at(m.string, m.start(), m.group(0), noun), s)
    return re.sub(rf"(?i)\b({_IT_ARTICLES})\s+({re.escape(noun)})",
                  lambda m: _cased_at(m.string, m.start(), m.group(1),
                                      articles.get(m.group(1).lower(), m.group(1) + " ")) + m.group(2), s)


_NEGATION = re.compile(r"(?i)\b(?:non|nessun\w*|senza|né|mai|nemmeno|neanche|not|no|never|without|neither|nor|lack\w*)\b|n't\b")
_EXISTENTIAL = re.compile(r"(?i)^(?:c'è|c'e'|ci\s+sono|esiste|emerge|si\s+registra|si\s+osserva|there\s+(?:is|was|are)|"
                          r"there's)\s*(?:un|uno|una|a|an)?$")
_BARE_ARTICLE = re.compile(r"(?i)^(?:il|lo|un|uno|the|a|an)$")


def _level_statement(s: str, m: re.Match, level_after: bool) -> bool:
    """Il livello di consenso e' un'affermazione sul consenso misurato: "Consenso alto ...", "il livello di
    consenso e' alto", "c'e' un consenso alto", "High consensus ...". Non in una frase negata ("non ha
    generato un consenso forte") ne' come complemento di un'altra frase ("costruire un consenso forte")."""
    clause = re.split(r"[,;:(]|\s[-–—]\s", s[:m.start()])[-1].strip(" *_\"«“")
    if _NEGATION.search(clause):
        return False
    if level_after and (re.search(r"(?i)livello|level", m.group(1)) or re.search(r"[:=]|\bè\b|\be'|\b(?:is|was|remains|risulta|era)\b", m.group(2))):
        return True
    return not clause or bool(_BARE_ARTICLE.match(clause) or _EXISTENTIAL.match(clause))


def _relabel_conviction(s: str, lang: str) -> str:
    """Il "consenso" scritto per la convinzione diventa uniformita' della convinzione."""
    words = t_value(lang, "report.consensus_rewording")
    noun = words["conviction_noun"]
    levels = t_value(lang, "report.conviction_uniformity_levels")
    s = _CONS_THEN_LEVEL.sub(lambda m: _cased_at(m.string, m.start(), m.group(1), noun) + m.group(2)
                             + levels[_cons_level_of(m.group(3))], s)
    s = _LEVEL_THEN_CONS.sub(lambda m: _cased_at(m.string, m.start(), m.group(1), words["level_before"].format(
        level=levels[_cons_level_of(m.group(1))], noun=noun)), s)
    return _replace_noun(s, noun, words["articles"])


def _fix_stance_level(s: str, level: str, lang: str) -> tuple[str, int]:
    """Il livello di consenso scritto dal modello diventa quello calcolato dalla posizione."""
    right = t(lang, f"report.consensus_levels.{level}")
    fixed = 0

    def after(m):
        nonlocal fixed
        if (_cons_level_of(m.group(3)) == level or not _level_statement(m.string, m, True)
                or _in_threshold_phrase(m.string, m.start())):
            return m.group(0)
        fixed += 1
        return m.group(1) + m.group(2) + _cased_at(m.string, m.start(3), m.group(3), right)

    def before(m):
        nonlocal fixed
        if (_cons_level_of(m.group(1)) == level or not _level_statement(m.string, m, False)
                or _in_threshold_phrase(m.string, m.start())):
            return m.group(0)
        fixed += 1
        return t_value(lang, "report.consensus_rewording")["stance_level_before"].format(
            level=_cased_at(m.string, m.start(), m.group(1), right), noun=m.group(3))

    s = _CONS_THEN_LEVEL.sub(after, s)
    s = _LEVEL_THEN_CONS.sub(before, s)
    return s, fixed


def fix_consensus_wording(md: str, stance: dict | None, lang: str = DEFAULT_LANGUAGE) -> tuple[str, dict]:
    """"Consenso"/"consensus" nel testo del modello vale solo per l'accordo sulla posizione.

    Con la posizione misurata: una frase che parla di convinzione (varianza, convinzione...) e non di
    posizione chiama il consenso "uniformita' della convinzione"; nelle altre frasi il livello di consenso
    scritto diventa quello calcolato. Senza posizione misurata il report non parla di consenso: le frasi
    con un livello di consenso o sulla convinzione si tolgono, nelle altre la parola diventa "posizioni
    prevalenti" solo nelle frasi sulle voci critiche ("inserite per stress-testare il consenso"), le altre
    frasi sul consenso si tolgono. Appendice, tabelle, titoli e codice restano come sono.
    Ritorna (report, {"relabelled", "level_fixed", "removed", "reworded"})."""
    info = {"relabelled": 0, "level_fixed": 0, "removed": 0, "reworded": 0}
    if not md:
        return md, info
    level = stance_consensus_level(stance)
    words = t_value(lang, "report.consensus_rewording")
    lines = md.split("\n")
    appendix = section_bounds(lines, APPENDIX_HEADING_RE)
    out, in_code = [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if (in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line)
                or (appendix and appendix[0] <= i < appendix[1]) or not _CONSENSUS_WORD.search(line)):
            out.append(line)
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        kept = []
        for s in _SENT_SPLIT.split(body):
            if not _CONSENSUS_WORD.search(s):
                kept.append(s)
                continue
            conviction = bool(_CONVICTION_CONTEXT.search(s)) and not _STANCE_CONTEXT.search(s)
            if level is None:
                if conviction or _LEVEL_PHRASE.search(s) or not _DISCLOSURE_CONTEXT.search(s):
                    info["removed"] += 1
                    continue
                s = _replace_noun(s, words["unmeasured_noun"], words["unmeasured_articles"])
                info["reworded"] += 1
            elif conviction:
                s = _relabel_conviction(s, lang)
                info["relabelled"] += 1
            else:
                s, n = _fix_stance_level(s, level, lang)
                info["level_fixed"] += n
            kept.append(s)
        rest = " ".join(kept).strip()
        if rest.strip("*_ :"):
            out.append(prefix + rest)
    if not any(info.values()):
        return md, info
    return _tidy("\n".join(out)), info


# ── Soglie del consenso: la tabella data al modello e il controllo delle soglie scritte ─────────────
# Il modello riceve la tabella esatta (consensus_threshold_lines). Una frase che, accanto a un livello di
# consenso, dichiara una soglia diversa ("un consenso medio sarebbe dal 75% in su": 75% e' la soglia di "alto")
# si toglie: la tabella delle metriche e l'appendice dicono gia' il livello giusto.

def consensus_threshold_lines(lang: str = DEFAULT_LANGUAGE) -> str:
    """Le soglie del consenso sulla posizione con le etichette del lettore, per il prompt del report."""
    pct = lambda v: f"{round(v * 100)}%"  # noqa: E731
    levels = t_value(lang, "report.consensus_levels")
    high, medium = pct(STANCE_CONSENSUS_HIGH_FROM), pct(STANCE_CONSENSUS_MEDIUM_FROM)
    return (f'    - "{levels["high"]}": {high} or more of the natural agents hold the most common stance\n'
            f'    - "{levels["medium"]}": from {medium} to below {high}\n'
            f'    - "{levels["low"]}": below {medium}, or two stances tied for the majority')


def _threshold_bounds() -> dict[str, dict[str, set[float]]]:
    high, medium = STANCE_CONSENSUS_HIGH_FROM * 100, STANCE_CONSENSUS_MEDIUM_FROM * 100
    return {"lower": {"high": {high}, "medium": {medium}, "low": {0.0}},
            "upper": {"high": {100.0}, "medium": {high}, "low": {medium}}}


_TH_NUM = r"(\d{1,3}(?:[.,]\d+)?)"
_TH_ART = r"(?:(?:la\s+)?soglia\s+(?:del|di)\s+|(?:the\s+)?threshold\s+of\s+)?(?:il\s+|l'|the\s+)?"
_TH_RANGE = re.compile(
    rf"(?i)\b(?:tra|fra|between)\s+{_TH_ART}{_TH_NUM}\s*%?\s+(?:e|and)\s+{_TH_ART}{_TH_NUM}\s*%|"
    rf"\b(?:dal|da|from)\s+{_TH_ART}{_TH_NUM}\s*%?\s+(?:al|a|to)\s+{_TH_ART}{_TH_NUM}\s*%|"
    rf"(?<![\d.,]){_TH_NUM}\s*%?\s*[-–—]\s*{_TH_NUM}\s*%")
_TH_LOWER = re.compile(
    rf"(?i)(?:\b(?:a\s+partire\s+dal?|dal|da|almeno|oltre|sopra|superiore\s+al?|pari\s+o\s+superiore\s+al?|"
    rf"super[aio]\w*|exceed\w*|"
    rf"richied\w*|servon\w*|serve|servirebb\w*|from|at\s+least|above|over|more\s+than|requires?|required|"
    rf"would\s+require|needs?|needed)\s+{_TH_ART}|[≥>]=?\s*){_TH_NUM}\s*%|"
    rf"(?<![\d.,]){_TH_NUM}\s*%\s*(?:in\s+su|o\s+più|o\s+piu'|o\s+oltre|or\s+(?:more|above|higher)|and\s+(?:above|up|over)|\+)")
_TH_UPPER = re.compile(
    rf"(?i)(?:\b(?:sotto|inferiore\s+al?|meno\s+del?|fino\s+al?|under|below|less\s+than|up\s+to)\s+{_TH_ART}|"
    rf"[≤<]=?\s*){_TH_NUM}\s*%|(?<![\d.,]){_TH_NUM}\s*%\s*(?:o\s+meno|or\s+(?:less|below|lower))")
# Una soglia e' dichiarata, non misurata: senza una di queste parole la frase parla del valore del run
_TH_CUE = re.compile(
    r"(?i)sogli\w*|threshold\w*|sarebb\w*|would|richied\w*|requir\w*|serv[eoi]\w*|need\w*|occorr\w*|bisogn\w*|"
    r"\bquando\b|\bwhen\b|\bse\b|\bif\b|significa|\bmeans?\b|corrispond\w*|correspond\w*|defin\w*|"
    r"in\s+su|o\s+più|or\s+(?:more|above)|and\s+above|[≥≤]|[<>]=")
_TH_LEVEL = re.compile(rf"(?i)\b({_CONS_LEVEL})\b")


def _th_value(raw: str) -> float:
    return float(raw.replace(",", "."))


def _stated_thresholds(sentence: str) -> list[tuple[str, tuple[float, ...], int]]:
    """(kind, valori, posizione) delle soglie scritte: range (a, b), lower (a), upper (b)."""
    found, masked = [], sentence
    for m in _TH_RANGE.finditer(sentence):
        a, b = [g for g in m.groups() if g is not None][:2]
        found.append(("range", (_th_value(a), _th_value(b)), m.start()))
        masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    seen = set()
    for kind, pattern in (("lower", _TH_LOWER), ("upper", _TH_UPPER)):
        for m in pattern.finditer(masked):
            value = _th_value(next(g for g in m.groups() if g is not None))
            if (kind, value) in seen:
                continue
            seen.add((kind, value))
            found.append((kind, (value,), m.start()))
    return found


def _level_near(sentence: str, pos: int) -> str | None:
    """Il livello di consenso della soglia a pos: il piu' vicino prima, altrimenti il primo dopo."""
    levels = [(m.start(), _cons_level_of(m.group(1))) for m in _TH_LEVEL.finditer(sentence)]
    before = [lv for p, lv in levels if p < pos]
    after = [lv for p, lv in levels if p >= pos]
    return before[-1] if before else after[0] if after else None


def wrong_consensus_threshold(sentence: str) -> dict | None:
    """{"level", "stated"} se la frase dichiara una soglia di consenso diversa dalla tabella, altrimenti None.
    Un intervallo accanto a un livello ("consenso medio (40-70%)") e' sempre una soglia; un limite solo con una
    parola di soglia nella frase ("sarebbe", "quando", "would"...): "oltre il 60% e' contrario" e' un valore."""
    if not _CONSENSUS_WORD.search(sentence) or not (_TH_CUE.search(sentence) or _TH_RANGE.search(sentence)):
        return None
    bounds = _threshold_bounds()
    for kind, values, pos in _stated_thresholds(sentence):
        level = _level_near(sentence, pos)
        if level is None:
            continue
        if kind == "range":
            ok = (any(abs(values[0] - v) < 0.5 for v in bounds["lower"][level])
                  and any(abs(values[1] - v) < 0.5 for v in bounds["upper"][level]))
        else:
            ok = any(abs(values[0] - v) < 0.5 for v in bounds[kind][level])
        if not ok:
            return {"level": level, "kind": kind, "stated": list(values)}
    return None


def fix_consensus_thresholds(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """Toglie le frasi che dichiarano una soglia di consenso sbagliata. Tabelle, titoli e codice restano.
    Ritorna (report, [{"sentence", "level", "kind", "stated"}])."""
    if not md:
        return md, []
    lines = md.split("\n")
    found, in_code = [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if (in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line)
                or not _CONSENSUS_WORD.search(line)):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        kept = []
        for s in _CLAIM_SENT_SPLIT.split(body):
            wrong = wrong_consensus_threshold(s)
            if wrong:
                found.append({"sentence": s[:200], **wrong})
                continue
            kept.append(s)
        if len(kept) != len(_CLAIM_SENT_SPLIT.split(body)):
            rest = " ".join(kept).strip()
            lines[i] = prefix + rest if rest.strip("*_ :") else ""
    return (_tidy("\n".join(lines)), found) if found else (md, [])


# ── Le metriche della convinzione non parlano di posizioni ────────────────────
# Polarizzazione ed entropia sono calcolate su opinion_strength (convinzione). Una frase che ne ricava le
# posizioni ("l'entropia indica posizioni consolidate") si toglie; una frase che dice che le posizioni non
# si sono mosse si toglie quando lo spostamento di posizione misurato e' moderato o ampio.

_NO_MOVE = re.compile(
    r"(?i)non\s+(?:ha|hanno|abbia|abbiano)\s+(?:\w+\s+){0,2}spostat\w*\s+(?:\w+\s+){0,2}posizion|"
    r"posizion\w*\s+(?:\w+\s+){0,3}(?:rimast\w+|restat\w+|sono)\s+(?:\w+\s+)?(?:stabil|invariat|ferm|immutat)|"
    r"opinioni\s+stabili|convinti\s+sono\s+rimasti\s+convinti|nessuno\s+ha\s+cambiato\s+(?:idea|posizione)|"
    r"did\s+not\s+(?:\w+\s+){0,2}(?:move|shift|change)\s+(?:\w+\s+){0,2}positions|"
    r"positions\s+(?:\w+\s+){0,3}(?:remained|stayed|were|are)\s+(?:\w+\s+)?(?:stable|unchanged|fixed)|"
    r"stable\s+opinions|convinced\s+stayed\s+convinced|no\s*one\s+changed\s+(?:their\s+)?(?:mind|position)")
_ENTROPY_WORD = re.compile(r"(?i)entropi|entropy")
_POSITION_WORD = re.compile(r"(?i)posizion|position")


def fix_position_claims(md: str, stance: dict | None, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """Toglie le frasi che leggono le posizioni nelle metriche della convinzione: entropia (o una sua lettura)
    e posizioni nella stessa frase; "le posizioni non si sono mosse" con spostamento moderato o ampio.
    Tabelle, titoli, codice, appendice e la riga canonica della confidenza restano.
    Ritorna (report, [{"reason", "sentence"}])."""
    if not md:
        return md, []
    shift = _shift_of(stance)[0] if stance_measured(stance) else None
    readings = {t(code, f"report.entropy.{k}").lower() for code in SUPPORTED_LANGUAGES for k in ("low", "mid", "high")}
    canonical = {t(code, "confidence.line").split("{")[0] for code in SUPPORTED_LANGUAGES}
    lines = md.split("\n")
    appendix = section_bounds(lines, APPENDIX_HEADING_RE)
    out, found, in_code = [], [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if (in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line)
                or (appendix and appendix[0] <= i < appendix[1]) or any(stripped.startswith(c) for c in canonical)):
            out.append(line)
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        kept = []
        for s in _CLAIM_SENT_SPLIT.split(body):
            low = s.lower()
            if (_ENTROPY_WORD.search(s) or any(r in low for r in readings)) and _POSITION_WORD.search(s):
                found.append({"reason": "entropy_positions", "sentence": s[:200]})
                continue
            if shift in ("moderate", "large") and _NO_MOVE.search(s):
                found.append({"reason": "positions_did_not_move", "shift": shift, "sentence": s[:200]})
                continue
            kept.append(s)
        if len(kept) == len(_CLAIM_SENT_SPLIT.split(body)):
            out.append(line)
            continue
        rest = " ".join(kept).strip()
        if rest.strip("*_ :"):
            out.append(prefix + rest)
    return (_tidy("\n".join(out)), found) if found else (md, [])


# ── Quote di posizione: appartengono al loro gruppo ───────────────────────────
# Una percentuale di posizione ("33,3% a favore") e' degli agenti naturali: accanto al nome di un segmento
# si toglie, salvo che sia la quota calcolata dal codice per quel segmento (stance.by_segment).

_STANCE_PCT = re.compile(
    r"(?i)(?<![\w.,])(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:(?:è|sono|e'|is|are)\s+)?"
    r"(a\s+favore|favorevol\w*|contrari\w*|neutral\w*|in\s+favou?r|support\w*|oppos\w*|against)")
_NATURAL_AGENTS = re.compile(r"(?i)agenti\s+naturali|natural\s+agents")
_SEGMENT_HINT = re.compile(r"(?i)\bsegment\w*|\btarget\b|\bcluster\b|\bgrupp\w*|\bgroups?\b")
# Parole dei nomi dei segmenti che non identificano un segmento
_GENERIC_SEGMENT_WORDS = {"consumatori", "consumers", "agenti", "agents", "esperti", "experts", "responsabili",
                          "settore", "sector", "clienti", "customers", "utenti", "users", "persone", "people"}


def _stance_of_word(word: str) -> str:
    w = word.lower()
    if w.startswith(("contrari", "oppos", "against")):
        return "oppose"
    if w.startswith("neutral"):
        return "neutral"
    return "support"


def _segment_mentions(text: str, words: dict[str, set[str]]) -> list[tuple[int, str | None]]:
    """(posizione, etichetta) di ogni parola dei nomi dei segmenti nel testo; le parole generiche ("segmento",
    "target", "cluster") sono menzioni di un segmento senza etichetta (None: nessun dato calcolato)."""
    out = []
    for label, ws in words.items():
        for w in ws:
            for m in re.finditer(rf"(?i)(?<![\w]){re.escape(w)}", text):
                out.append((m.start(), label))
    out += [(m.start(), None) for m in _SEGMENT_HINT.finditer(text)]
    return sorted(out, key=lambda x: x[0])


def _segment_values(seg: dict, key: str) -> list[float]:
    """Quote (in punti percentuali) calcolate per il segmento per la posizione key, anche sommata a un'altra
    posizione ("contrari o neutrali")."""
    shares = {k: v * 100 for k, v in seg["final"]["shares"].items()}
    return [shares[key]] + [shares[key] + v for k, v in shares.items() if k != key]


def fix_segment_stance_shares(md: str, stance: dict | None, segments: list[dict] | None,
                              lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """Una percentuale di posizione appartiene al segmento a cui e' attaccata nella sua proposizione (la
    menzione di segmento piu' vicina prima della cifra, nella parentesi o nella proposizione), mai a un
    segmento nominato altrove nella frase. Con "agenti naturali" nella proposizione, o detto prima nella frase
    senza un segmento in mezzo, la cifra e' degli agenti naturali e resta. Attaccata a un segmento:
    resta se e' una quota calcolata per quel segmento (segmenti con almeno SEGMENT_STANCE_MIN_AGENTS agenti);
    per un segmento piu' piccolo diventa il conteggio ("1 su 1 contrario") se corrisponde; altrimenti si
    toglie: dentro una parentesi la sola cifra, fuori dalla parentesi tutta la frase.
    Ritorna (report, [{"action", "removed", "segment", "sentence"}])."""
    if not md or not stance_measured(stance):
        return md, []
    words = {}
    for seg in segments or []:
        label = str(seg.get("label") or "")
        words[label] = {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{5,}", label)} - _GENERIC_SEGMENT_WORDS
    computed = {seg["label"]: seg for seg in stance.get("by_segment") or []}
    lines = md.split("\n")
    appendix = section_bounds(lines, APPENDIX_HEADING_RE)
    found, in_code = [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if (in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line)
                or (appendix and appendix[0] <= i < appendix[1]) or not _STANCE_PCT.search(line)):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        sentences = []
        for s in _CLAIM_SENT_SPLIT.split(body):
            drop = False
            for m in reversed(list(_STANCE_PCT.finditer(s))):
                start, end = m.start(), m.end()
                opened = s.rfind("(", 0, start)
                in_paren = opened != -1 and s.count(")", opened, start) == 0
                anchor = opened if in_paren else start
                clause_start = max(s.rfind(c, 0, anchor) for c in ",;") + 1
                if in_paren:
                    close = s.find(")", end)
                    clause_end = close if close != -1 else len(s)
                else:
                    ends = [p for p in (s.find(",", end), s.find(";", end)) if p != -1]
                    clause_end = min(ends) if ends else len(s)
                clause = s[clause_start:clause_end]
                if _NATURAL_AGENTS.search(clause):
                    continue
                before = [(p, label) for p, label in _segment_mentions(clause, words) if p < start - clause_start]
                if not before:
                    continue  # not attached to a segment
                # The nearest segment named by its label wins over a generic word right before it
                seg_pos, label = before[-1]
                named = [(p, lb) for p, lb in before if lb is not None]
                if label is None and named and seg_pos - named[-1][0] <= 40:
                    seg_pos, label = named[-1]
                qualifier = list(_NATURAL_AGENTS.finditer(s[:start]))
                if qualifier and qualifier[-1].start() > clause_start + seg_pos:
                    continue
                value = float(m.group(1).replace(",", "."))
                key = _stance_of_word(m.group(2))
                seg = computed.get(label)
                entry = {"removed": m.group(0), "segment": label, "sentence": s[:200]}
                if seg and seg.get("agents", 0) >= SEGMENT_STANCE_MIN_AGENTS:
                    if any(abs(v - value) <= 0.05 for v in _segment_values(seg, key)):
                        continue
                elif seg and seg["final"].get("measured"):
                    final = seg["final"]
                    if abs(final["counts"][key] / final["measured"] * 100 - value) <= 0.05:
                        count_text = t(lang, "report.stance.count_share", count=final["counts"][key],
                                       total=final["measured"], label=_stance_label(key, lang))
                        s = s[:start] + count_text + s[end:]
                        found.append({**entry, "action": "as_count"})
                        continue
                if in_paren:
                    lead = re.search(r"[,;]?\s*$", s[:start])
                    s = s[:lead.start() if lead else start] + s[end:]
                    found.append({**entry, "action": "removed"})
                else:
                    drop = True
                    found.append({**entry, "action": "sentence_removed"})
                    break
            if drop:
                continue
            s = re.sub(r"\(\s*[,;]\s*", "(", s)
            s = re.sub(r"\(\s*\)", "", s)
            s = re.sub(r"\s+([,.;:)])", r"\1", s)
            sentences.append(s)
        new = prefix + " ".join(sentences) if " ".join(sentences).strip() else ""
        if new != line:
            lines[i] = new
    return (_tidy("\n".join(lines)), found) if found else (md, [])


# ── 6. Controllo finale: niente frammenti ─────────────────────────────────────
# Dopo tutte le sostituzioni: un articolo seguito da una congiunzione, un verbo o la punteggiatura ("il e il",
# "e il è", "the and") e' un frammento: la frase si toglie. Parentesi vuote, spazi prima della punteggiatura
# e virgole doppie si correggono sul posto.

_DANGLING = re.compile(
    # "gli è", "le è" are pronouns (grammatical): only articles that cannot be pronouns before a verb
    r"\b(?:il|lo|la|un|uno|una|del|della|dello|al|alla|allo)\s+(?:e|ed|o|è|sono|era|erano)\b|"
    r"\b(?:gli|le|dei|degli|delle|ai|agli|alle)\s+(?:e|ed|o)\b|"
    r"\b(?:il|lo|la|gli|le|un|uno|una)\s*[,.;:]|\b(?:e|ed|o)\s+(?:e|ed|o)\b|"
    r"\b(?:the|an)\s+(?:and|or|is|are|was|were)\b|\b(?:the|a|an|of)\s*[,.;:]|\b(?:and|or)\s+(?:and|or)\b")
_REPAIRS = ((re.compile(r"\(\s*[,;:]?\s*\)"), ""), (re.compile(r"\(\s*[,;:]\s*"), "("),
            (re.compile(r"\s*[,;:]\s*\)"), ")"), (re.compile(r"[ \t]+([,.;:!?)])"), r"\1"),
            (re.compile(r",\s*,"), ","), (re.compile(r"(?<=\S)[ \t]{2,}(?=\S)"), " "))


def repair_text(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """Ultimo passaggio: corregge i resti delle sostituzioni e toglie le frasi rimaste spezzate.
    Tabelle, titoli e codice restano. Ritorna (report, [{"action": "fixed"|"removed", "sentence"}])."""
    if not md:
        return md, []
    lines = md.split("\n")
    found, in_code = [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        kept, changed = [], False
        for s in _CLAIM_SENT_SPLIT.split(body):
            fixed = s
            for pattern, repl in _REPAIRS:
                fixed = pattern.sub(repl, fixed)
            if _DANGLING.search(fixed):
                found.append({"action": "removed", "sentence": s[:200]})
                changed = True
                continue
            if fixed != s:
                found.append({"action": "fixed", "sentence": s[:200]})
                changed = True
            kept.append(fixed)
        if changed:
            rest = " ".join(kept).strip()
            lines[i] = prefix + rest if rest.strip("*_ :") else ""
    return (_tidy("\n".join(lines)), found) if found else (md, [])


# ── Riferimenti rimasti senza la frase a cui puntavano ──────────────────────────────────────────────
# Un controllo toglie una frase; la successiva puo' cominciare riferendosi a lei ("Questa dispersione, combinata
# con..."). Si confronta il testo prima e dopo il controllo frase per frase: se la frase subito prima di una
# frase rimasta e' stata tolta e la frase rimasta comincia con un dimostrativo, il connettivo che rimanda
# indietro si toglie ("Per questo, X" -> "X"), altrimenti si toglie la frase; poi la successiva, se anche lei
# rimanda indietro.

_ORPHAN_REF = re.compile(
    r"(?i)^[\"«(*_]*(?:(?:e|ed|ma|and|but)\s+)?(?:quest[oaie]|ciò|cio'|tale|tali|this|these|that|those|such|"
    r"la\s+sua|le\s+sue|il\s+suo|i\s+suoi|his|her|he|she)\b")
# Dimostrativi che indicano il report o la simulazione, non la frase prima
_ORPHAN_CONTEXT = re.compile(
    r"(?i)^[\"«(*_]*(?:quest[oaie]|this|these)\s+(?:report\w*|rapport\w*|simulazion\w*|simulation\w*|analisi|"
    r"analys[ie]s|sezion\w*|section\w*|document\w*|studi\w*|stud(?:y|ies)|stress[- ]test\w*|test)\b")
_ORPHAN_CONNECTIVE = re.compile(
    r"(?i)^([\"«(*_]*)(?:per\s+quest[oi](?:\s+motiv[oi])?|per\s+ciò|in\s+quest[oa]\s+(?:contesto|quadro|scenario|"
    r"senso|caso)|oltre\s+a\s+(?:questo|ciò)|nonostante\s+(?:questo|ciò)|ciò\s+nonostante|a\s+fronte\s+di\s+(?:questo|ciò)|"
    r"because\s+of\s+this|for\s+this\s+reason|in\s+this\s+(?:context|light|sense|scenario|case)|despite\s+this|"
    r"beyond\s+this|given\s+this|on\s+top\s+of\s+this|as\s+a\s+result\s+of\s+this)\s*,?\s+(?=\S)")


def _sentence_tokens(md: str) -> list[tuple[str, int, int, str]]:
    """(kind, riga, indice della frase, testo). S: frase di una riga di testo; B: fine della riga (un a capo:
    il paragrafo seguente puo' ancora rimandare a questo); H: titolo, tabella o codice (chiude il rimando)."""
    tokens, in_code = [], False
    for i, line in enumerate(md.split("\n")):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            tokens.append(("H", i, 0, stripped))
            continue
        if not stripped:
            continue
        if in_code or stripped.startswith("|") or _ANY_HEADING.match(line):
            tokens.append(("H", i, 0, stripped))
            continue
        body = _LINE_PREFIX.match(line).group(2)
        for k, s in enumerate(_CLAIM_SENT_SPLIT.split(body)):
            if s.strip():
                tokens.append(("S", i, k, s.strip()))
        tokens.append(("B", i, 0, ""))
    return tokens


def _token_key(tok: tuple[str, int, int, str]) -> str:
    return tok[0] + re.sub(r"\s+", " ", tok[3])


def _similar(a: str, b: str) -> bool:
    import difflib
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.6


def repair_orphan_references(before: str, after: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """after = before passato da un controllo che toglie frasi. Ripara o toglie le frasi di after che cominciano
    rimandando a una frase tolta. Ritorna (report, [{"action": "reference_repaired"|"reference_removed",
    "sentence", "removed_before"}])."""
    if not after or before == after:
        return after, []
    import difflib
    a, b = _sentence_tokens(before), _sentence_tokens(after)
    ops = difflib.SequenceMatcher(None, [_token_key(x) for x in a], [_token_key(x) for x in b],
                                  autojunk=False).get_opcodes()
    starts: dict[int, str] = {}  # indice in b della prima frase rimasta dopo una frase tolta -> frase tolta
    for tag, i1, i2, j1, j2 in ops:
        if tag not in ("delete", "replace"):
            continue
        # La frase tolta: l'ultima del blocco, dopo di lei solo a capo
        k = i2 - 1
        while k >= i1 and a[k][0] == "B":
            k -= 1
        if k < i1 or a[k][0] != "S":
            continue
        if tag == "replace" and any(t[0] == "S" and _similar(t[3], a[k][3]) for t in b[j1:j2]):
            continue
        # La frase rimasta subito dopo: si salta un a capo, mai un titolo, una tabella o del codice
        j = j2
        while j < len(b) and b[j][0] == "B":
            j += 1
        if j < len(b) and b[j][0] == "S":
            starts[j] = a[k][3]
    if not starts:
        return after, []
    edits: dict[tuple[int, int], str | None] = {}
    found = []
    for j, removed in sorted(starts.items()):
        while j < len(b) and b[j][0] == "S":
            s = b[j][3]
            m = _ORPHAN_CONNECTIVE.match(s)
            if not m and (not _ORPHAN_REF.match(s) or _ORPHAN_CONTEXT.match(s)):
                break
            rest = s[m.end():] if m else ""
            if m and not _ORPHAN_REF.match(rest):
                fixed = m.group(1) + rest[:1].upper() + rest[1:]
                edits[(b[j][1], b[j][2])] = fixed
                found.append({"action": "reference_repaired", "sentence": s[:200], "removed_before": removed[:200]})
                break
            edits[(b[j][1], b[j][2])] = None
            found.append({"action": "reference_removed", "sentence": s[:200], "removed_before": removed[:200]})
            removed = s
            j += 1
            while j < len(b) and b[j][0] == "B":
                j += 1
    lines = after.split("\n")
    for line_idx in sorted({li for li, _ in edits}):
        prefix, body = _LINE_PREFIX.match(lines[line_idx]).groups()
        parts = _CLAIM_SENT_SPLIT.split(body)
        kept = []
        for k, s in enumerate(parts):
            if (line_idx, k) not in edits:
                kept.append(s)
            elif edits[(line_idx, k)] is not None:
                kept.append(edits[(line_idx, k)])
        rest = " ".join(kept).strip()
        lines[line_idx] = prefix + rest if rest.strip("*_ :") else ""
    return _tidy("\n".join(lines)), found


# ── Una sezione non comincia con un riferimento a qualcosa che non c'e' ───────
_DANGLING_START = re.compile(
    r"(?i)^[\"«“(*_]*(?:la\s+sua|le\s+sue|il\s+suo|i\s+suoi|lui|lei|egli|ella|esso|essa|costui|costei|his|her|he|she|him)\b")


def fix_dangling_section_starts(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, list[dict]]:
    """La prima frase di una sezione '## ' che comincia con un pronome o un possessivo ("La sua opinione",
    "Her opinion") o un dimostrativo senza antecedente si toglie, e cosi' le seguenti dello stesso paragrafo
    che fanno lo stesso. Ritorna (report, [{"action": "dangling_start_removed", "sentence"}])."""
    if not md:
        return md, []
    lines = md.split("\n")
    found = []
    for i, line in enumerate(lines):
        m = _TOP_HEADING.match(line)
        if not m or len(m.group(1)) != 2:
            continue
        j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
        if j is None or _ANY_HEADING.match(lines[j]) or lines[j].strip().startswith(("|", "```")):
            continue
        prefix, body = _LINE_PREFIX.match(lines[j]).groups()
        parts = _CLAIM_SENT_SPLIT.split(body)
        k = 0
        while k < len(parts) and (_DANGLING_START.match(parts[k])
                                  or (_ORPHAN_REF.match(parts[k]) and not _ORPHAN_CONTEXT.match(parts[k]))):
            found.append({"action": "dangling_start_removed", "sentence": parts[k][:200]})
            k += 1
        if k:
            rest = " ".join(parts[k:]).strip()
            lines[j] = prefix + rest if rest.strip("*_ :") else ""
    return (_tidy("\n".join(lines)), found) if found else (md, [])


# ── Parametri della simulazione nell'appendice: dal codice ────────────────────

def appendix_parameters(values: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """Le righe dei parametri (template, agenti, round, topic, domanda) dai dati salvati della simulazione."""
    p = t_value(lang, "report.parameters")
    missing = p["not_specified"]

    def value(key):
        v = values.get(key)
        return str(v).strip() if v not in (None, "") and str(v).strip() else missing
    return "\n".join(f"- {p[key]}: {value(key)}" for key in ("template", "agents", "rounds", "topic", "question"))


def ensure_appendix_parameters(md: str, block: str | None, lang: str = DEFAULT_LANGUAGE) -> tuple[str, str]:
    """Nell'appendice le righe dei parametri sono quelle del codice: sostituite sotto il titolo
    "**Parametri della simulazione:**" (in qualsiasi lingua), o aggiunte in testa all'appendice.
    Ritorna (report, "replaced" | "inserted" | "no_appendix" | "")."""
    if not md or not block:
        return md, ""
    lines = md.split("\n")
    bounds = section_bounds(lines, APPENDIX_HEADING_RE)
    if not bounds:
        return md, "no_appendix"
    headings = {t(code, "report.parameters.heading").strip("*: ").lower() for code in SUPPORTED_LANGUAGES}
    head = next((k for k in range(bounds[0] + 1, bounds[1])
                 if lines[k].strip().strip("*: ").lower() in headings), None)
    if head is None:
        lines[bounds[0] + 1:bounds[0] + 1] = ["", t(lang, "report.parameters.heading"), *block.split("\n"), ""]
        return _tidy("\n".join(lines)), "inserted"
    k = head + 1
    while k < bounds[1] and not lines[k].strip():
        k += 1
    end = k
    while end < bounds[1] and re.match(r"^\s*[-*]\s", lines[end]):
        end += 1
    lines[head + 1:end] = block.split("\n")
    return _tidy("\n".join(lines)), "replaced"


# ── Etichette del lettore a meta' frase: minuscola ────────────────────────────

def fix_label_case(md: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, int]:
    """Le etichette delle metriche ("Entropia della convinzione (ultimo round)") copiate a meta' frase prendono
    la minuscola ("l'entropia della convinzione"); a inizio frase e nelle tabelle restano come sono."""
    if not md:
        return md, 0
    labels = [v for v in t_value(lang, "report.labels").values() if v[:1].isupper() and len(v) > 5]
    labels += [v for v in t_value(lang, "debate.rows").values() if v[:1].isupper() and len(v) > 5]
    pattern = re.compile("(?<![\\w])(" + "|".join(re.escape(v) for v in sorted(set(labels), key=len, reverse=True)) + ")")
    lines = md.split("\n")
    count, in_code = 0, False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code or not stripped or stripped.startswith("|") or _ANY_HEADING.match(line):
            continue

        def repl(m):
            nonlocal count
            before = m.string[:m.start()]
            sentence_start = not before.strip() or re.search(r"[.!?]\s*[\"«(*_]*$|\*\*:?\s*$|^\s*(?:[-*+>]|\d+[.)])\s*$", before)
            if sentence_start:
                return m.group(0)
            count += 1
            return m.group(0)[:1].lower() + m.group(0)[1:]

        lines[i] = pattern.sub(repl, line)
    return ("\n".join(lines), count) if count else (md, 0)


# ── Livello di confidenza (deterministico) ────────────────────────────────────
# Il livello parte dalla stabilita' delle posizioni ed e' limitato dalla numerosita' del campione.
# Stabilita' (stance_stability): consenso sulla posizione degli agenti naturali e spostamento tra la prima
# e l'ultima misura, con le soglie della tabella qui sopra:
#   - "bassa": consenso basso (nessuna posizione supera la meta') o spostamento ampio
#   - "alta": consenso alto e posizioni stabili (serve almeno un agente rimisurato)
#   - "media": il resto
# Prima la stabilita' veniva dalla variance di opinion_strength e dall'entropia dei suoi bucket: misurano
# quanto e' simile l'intensita' delle convinzioni, non se gli agenti concordano ne' se cambiano posizione.
# Resta solo per le simulazioni salvate senza posizione (_stability_level), per non cambiarne il livello.
# Soglie del campione:
#   - piccolo (al massimo "bassa", indicativa): < 20 agenti, < 5 round o < 50 post.
#     Con meno di 20 agenti un solo agente sposta la distribuzione di oltre 5 punti e i 5 bucket di
#     get_opinion_distribution hanno in media meno di 4 agenti. Le opinioni si aggiornano ogni
#     3 round (OPINION_UPDATE_INTERVAL): sotto i 5 round c'e' al massimo un aggiornamento, e
#     polarization_delta, echo chamber e diversita' lavorano su 2-4 punti. Sotto i 50 post i
#     conteggi dei topic emergenti e delle citazioni sono a una cifra.
#   - medio (al massimo "media"): < 50 agenti, < 10 round o < 200 post.
#     A 10 round ci sono 3 aggiornamenti delle opinioni ed e' entrato almeno un evento di
#     diversita' (DIVERSITY_INJECT_INTERVAL); 200 post sono il feed salvato per le citazioni.
#   - grande: nessun limite oltre la stabilita'.
CONFIDENCE_LEVELS = ("bassa", "media", "alta")
CONFIDENCE_SCORES = {"bassa": 0.3, "media": 0.55, "alta": 0.8}  # confidence_score salvato, per compatibilita'
SMALL_SAMPLE = {"agents": 20, "rounds": 5, "posts": 50}
MEDIUM_SAMPLE = {"agents": 50, "rounds": 10, "posts": 200}


def confidence_rule_text(lang: str = DEFAULT_LANGUAGE) -> str:
    """Le soglie del campione, per l'appendice."""
    return t(lang, "confidence.rule",
             **{f"small_{k}": v for k, v in SMALL_SAMPLE.items()},
             **{f"medium_{k}": v for k, v in MEDIUM_SAMPLE.items()})


def _level_word(level: str, lang: str) -> str:
    """Livello interno (bassa/media/alta) come parola del lettore, minuscola."""
    return t(lang, f"confidence.levels.{level}").lower()


def _stability_level(variance: float | None, entropy: float | None) -> str:
    if variance is None or entropy is None:
        return "bassa"
    # Soglie di variance della regola di confidenza (invariate); entropia dalla tabella delle letture
    reading = entropy_reading(entropy)
    if variance > 0.15 or reading == "high":
        return "bassa"
    if variance >= 0.05 or reading == "mid":
        return "media"
    return "alta"


def stance_stability(stance: dict | None) -> str | None:
    """bassa | media | alta dalla posizione (consenso e spostamento); None se non misurata."""
    level = stance_consensus_level(stance)
    if level is None:
        return None
    shift, _ = _shift_of(stance)
    if level == "low" or shift == "large":
        return "bassa"
    # Posizioni stabili su pochi agenti rimisurati non bastano per una confidenza alta
    if level == "high" and shift == "stable" and stance["shift"]["remeasured"] >= STANCE_SHIFT_MIN_REMEASURED:
        return "alta"
    return "media"


def assess_confidence(agents: int, rounds: int, posts: int, variance: float | None,
                      entropy: float | None, lang: str = DEFAULT_LANGUAGE, stance: dict | None = None) -> dict:
    """Livello di confidenza dal campione e dalla stabilita'. Il modello puo' spiegarlo, non cambiarlo."""
    sample = {"agents": int(agents or 0), "rounds": int(rounds or 0), "posts": int(posts or 0)}
    small = [k for k, v in SMALL_SAMPLE.items() if sample[k] < v]
    medium = [k for k, v in MEDIUM_SAMPLE.items() if sample[k] < v]
    size, cap = ("small", "bassa") if small else ("medium", "media") if medium else ("large", "alta")
    from_stance = stance_stability(stance)
    stability = from_stance or _stability_level(variance, entropy)
    level = min(stability, cap, key=CONFIDENCE_LEVELS.index)
    # level, sample_cap e stability restano i codici interni (bassa/media/alta): li legge la UI
    label = t(lang, f"confidence.levels.{level}") + (t(lang, "confidence.indicative_suffix") if size == "small" else "")

    parts = [t(lang, "confidence.sample_counts", **sample)]
    limits = small or medium
    if limits:
        bound = SMALL_SAMPLE if small else MEDIUM_SAMPLE
        why = ", ".join(t(lang, "confidence.fewer_than", count=bound[k], noun=t(lang, f"confidence.nouns.{k}"))
                        for k in limits)
        parts.append(t(lang, "confidence.sample_small" if small else "confidence.sample_medium",
                       why=why, cap=_level_word(cap, lang)))
    if from_stance:
        parts.append(t(lang, "confidence.stability_stance", consensus=stance_consensus_text(stance, lang),
                       group=t(lang, f"report.stance.groups.{stance['agreement']['group']}"),
                       shift=stance_shift_label(stance, lang),
                       stability=_level_word(stability, lang)))
    elif variance is not None and entropy is not None:
        parts.append(t(lang, "confidence.stability", variance=fmt_number(variance, 3, lang),
                       entropy=fmt_number(entropy, 3, lang), stability=_level_word(stability, lang)))
    return {
        "level": level,
        "label": label,
        "score": CONFIDENCE_SCORES[level],
        "sample_size": size,
        "sample_cap": cap,
        "stability": stability,
        "stability_source": "stance" if from_stance else "conviction",
        "stance_consensus": stance_consensus_level(stance),
        "variance": variance,
        "entropy": entropy,
        "entropy_reading": entropy_label(entropy, lang),
        **sample,
        "basis": "; ".join(parts),
    }


def confidence_prompt_block(conf: dict) -> str:
    reading = (f"Opinion entropy reading: {conf['entropy_reading']} (use this reading as is wherever you cite "
               "the opinion entropy; never derive another one).\n") if conf.get("entropy_reading") else ""
    return (f"Confidence level: {conf['label']}\n"
            f"Computed from: {conf['basis']}.\n"
            f"{reading}"
            "Report this level exactly as it is (in the executive summary and in the confidence assessment "
            "section): you may explain it, never raise or lower it.")


def confidence_line(conf: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    return t(lang, "confidence.line", label=conf["label"], basis=conf["basis"])


_LEVEL_WORD = (r"molto\s+alt[oa]|medio[-\s]alt[oa]|medio[-\s]bass[oa]|medium[-\s]high|medium[-\s]low|"
               r"very\s+high|very\s+low|"
               r"alt[oa]|elevat[oa]|high|medi[oa]|medium|moderat[oae]|bass[oa]|low|indicativ[oae]")
_CONF_NOUN = (r"(?:level\s+of\s+)?confidence(?:\s+(?:score|level))?|(?:livello\s+di\s+|grado\s+di\s+)?confidenza|"
              r"affidabilit[àa]")
_CONF_THEN_LEVEL = re.compile(
    rf"(?i)\b({_CONF_NOUN})((?:\*\*)?\s*(?:[:=]|\bè\b|\be'|\bis\b)?\s*(?:\*\*)?\s*)({_LEVEL_WORD})\b(\s*\((?:indicativ[oae][^)]*)\))?")
_LEVEL_THEN_CONF = re.compile(rf"(?i)\b({_LEVEL_WORD})(\s+)(confidenza|affidabilit[àa]|confidence)\b")


def _level_of(word: str) -> str:
    w = re.sub(r"[-\s]+", " ", word.lower())
    if w.startswith(("bass", "low", "indicativ", "medio bass", "medium low", "very low")):
        return "bassa"
    if w.startswith(("molto", "alt", "elevat", "high", "medio alt", "medium high", "very high")):
        return "alta"
    return "media"


_THRESHOLD_WORDS = re.compile(
    r"(?i)sogli\w*|threshold\w*|minim\w*|requisit\w*|requir\w*|necessar\w*|almeno|at\s+least|servon\w*|"
    r"servirebb\w*|would\s+need|needed|per\s+(?:ottenere|raggiungere)|to\s+(?:reach|get|obtain)")


def _in_threshold_phrase(text: str, pos: int) -> bool:
    """Il livello a pos descrive una soglia ("sotto le soglie minime per confidenza media (50 agenti...)"):
    una parola di soglia prima, nella stessa frase, entro 80 caratteri."""
    window = text[max(0, pos - 80):pos]
    window = re.split(r"[.!?]\s", window)[-1]
    return bool(_THRESHOLD_WORDS.search(window))


def _line_copy_re(line: str) -> re.Pattern:
    """La riga com'e', con o senza grassetto/corsivo e con spazi diversi."""
    words = [w.strip("*_") for w in line.split() if w.strip("*_")]
    return re.compile(r"(?i)[*_]*" + r"[*_\s]*".join(re.escape(w) for w in words) + r"[*_]*\.?")


def drop_confidence_line_copies(md: str, canonical: str) -> tuple[str, int]:
    """Toglie le copie della riga di confidenza del codice scritte dal modello (la riga resta una sola:
    quella che enforce_confidence mette in testa alla sezione). Tabelle e codice restano."""
    pattern = _line_copy_re(canonical)
    lines, removed, in_code = md.split("\n"), 0, False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code or line.strip().startswith("|") or _ANY_HEADING.match(line) or not pattern.search(line):
            continue
        prefix, body = _LINE_PREFIX.match(line).groups()
        body, n = pattern.subn("", body)
        removed += n
        body = re.sub(r"[ \t]{2,}", " ", body).strip()
        lines[i] = prefix + body if body.strip("*_ :.—-") else ""
    return (_tidy("\n".join(lines)), removed) if removed else (md, 0)


def enforce_confidence(md: str, conf: dict, lang: str = DEFAULT_LANGUAGE,
                       stats: dict | None = None) -> tuple[str, int]:
    """Il livello del modello non vale: ogni livello dichiarato diventa quello calcolato, e la sezione
    Confidence Assessment si apre con la riga deterministica, l'unica: le copie del modello si tolgono.
    Ritorna (report, livelli corretti); stats, se dato, riceve {"line_copies_removed": n}."""
    if not md:
        return md, 0
    label = conf["label"]
    overrides = 0

    def conf_then_level(m):
        nonlocal overrides
        if _in_threshold_phrase(m.string, m.start()):
            return m.group(0)
        if _level_of(m.group(3)) != conf["level"] or (conf["sample_size"] == "small" and not m.group(4)):
            overrides += _level_of(m.group(3)) != conf["level"]
            return f"{m.group(1)}{m.group(2)}{label.lower() if m.group(3).islower() else label}"
        return m.group(0)

    def level_then_conf(m):
        nonlocal overrides
        if _in_threshold_phrase(m.string, m.start()):
            return m.group(0)
        if _level_of(m.group(1)) != conf["level"]:
            overrides += 1
            return f"{m.group(3)} {label.lower()}"
        return m.group(0)

    out, in_code = [], False
    for line in md.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and not line.strip().startswith("|") and not _ANY_HEADING.match(line):
            line = _CONF_THEN_LEVEL.sub(conf_then_level, line)
            line = _LEVEL_THEN_CONF.sub(level_then_conf, line)
        out.append(line)
    lines = out

    canonical = confidence_line(conf, lang)
    deduped, copies = drop_confidence_line_copies("\n".join(lines), canonical)
    if stats is not None:
        stats["line_copies_removed"] = copies
    lines = deduped.split("\n")
    bounds = section_bounds(lines, CONFIDENCE_HEADING_RE)
    if bounds:
        lines[bounds[0] + 1:bounds[0] + 1] = ["", canonical, ""]
    else:
        section = [f"## {t(lang, 'report.headings.confidence_assessment')}", "", canonical, ""]
        anchor = section_bounds(lines, APPENDIX_HEADING_RE)
        if anchor:
            lines[anchor[0]:anchor[0]] = section
        else:
            lines += ["", *section]
    return _tidy("\n".join(lines)), overrides


# ── Scenari senza probabilita' numeriche ──────────────────────────────────────

_NUM = r"\d{1,3}(?:[.,]\d+)?"
_PCT_VALUE = rf"~?\s*{_NUM}\s*%"
_PCT_RANGE = (rf"(?:(?:tra|fra|dal|da|between|from)\s+(?:il\s+|l'|the\s+)?)?~?\s*{_NUM}\s*%?\s*"
              rf"(?:[-–—]|\b(?:e|al|a|to|and)\b(?:\s+il)?)\s*~?\s*{_NUM}\s*%")
_PROB_WORD = r"probabilit[àa]|probability|likelihood|chances?|verosimiglianza"
_PROB_PHRASE = re.compile(
    rf"(?i)(?:\s*\b(?:con|with)\s+(?:una\s+|a\s+)?)?\(?\s*(?:\*\*)?(?:{_PROB_WORD})(?:\s+(?:stimata|stimato|estimated|attesa|indicativa|di\s+accadimento))?"
    rf"\s*(?:\*\*)?\s*[:=]?\s*(?:\*\*)?\s*(?:del(?:l')?\s+|of\s+|pari\s+al?\s+|circa\s+|around\s+|~\s*)?"
    rf"(?:{_PCT_RANGE}|{_PCT_VALUE})(?:\s*(?:\*\*))?\s*\)?")
_PROB_AFTER = re.compile(
    rf"(?i)\s*\(?\s*(?:{_PCT_RANGE}|{_PCT_VALUE})\s+(?:di\s+)?(?:{_PROB_WORD}|likely|probabile)\b\s*\)?")
_RANGE_RE = re.compile(rf"(?i)\(?\s*{_PCT_RANGE}\s*\)?")
_PCT_RE = re.compile(rf"\(?\s*{_PCT_VALUE}\s*\)?")
_BOLD_TITLE = re.compile(r"^(\s*(?:[-*+]\s+)?\*\*)(.+?)(\*\*)")
_PROB_HEADER = re.compile(rf"(?i){_PROB_WORD}|plausibilit")


def _clean(line: str) -> str:
    line = re.sub(r"\(\s*[,;:–—-]?\s*\)", "", line)
    line = re.sub(r"(?i)\b(?:probabilit[àa]|probability|likelihood)(?:\s+stimata|\s+estimated)?\s*:\s*(?=$|[.;,)])", "", line)
    line = re.sub(r"(?<![.])([.!?])\s*[.;,](?![.])", r"\1", line)
    line = re.sub(r"([,;])\s*[,;]", r"\1", line)
    line = re.sub(r":\s*\.", ".", line)
    line = re.sub(r"\s+([.,;:)])", r"\1", line)
    line = re.sub(r"\s*[–—-]\s*$", "", line)
    line = re.sub(r"\*\*\s*\*\*", "", line)
    line = re.sub(r"[ \t]{2,}", " ", line)
    return line.rstrip()


def _strip_title_pct(line: str) -> tuple[str, int]:
    """Percentuali nel titolo di uno scenario ('### ...' o '**...**'), non nel testo che lo segue."""
    if re.match(r"^\s*#{3,6}\s", line):
        return _PCT_RE.subn("", line)
    m = _BOLD_TITLE.match(line)
    if not m:
        return line, 0
    title, n = _PCT_RE.subn("", m.group(2))
    if not n:
        return line, 0
    return m.group(1) + title.strip() + m.group(3) + line[m.end():], n


def strip_scenario_probabilities(md: str) -> tuple[str, int]:
    """Toglie probabilita' e intervalli percentuali dagli scenari. Ritorna (report, valori tolti).

    In tutto il report: le probabilita' esplicite ("probabilità: 65-75%"). Nella sezione scenari
    anche gli intervalli percentuali, le percentuali nei titoli degli scenari e le colonne
    "probabilità" delle tabelle. Le percentuali di dati ("il 40% degli agenti") restano.
    """
    if not md:
        return md, 0
    lines = md.split("\n")
    bounds = section_bounds(lines, SCENARIO_HEADING_RE)
    stripped = 0
    prob_cols: set[int] = set()
    for i, line in enumerate(lines):
        if _ANY_HEADING.match(line) and not line.lstrip().startswith("###"):
            prob_cols = set()
            continue
        in_scen = bounds is not None and bounds[0] < i < bounds[1]
        new = line
        if line.strip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            if any(_PROB_HEADER.search(c) for c in cells) and not re.search(r"\d", line):
                prob_cols = {j for j, c in enumerate(cells) if _PROB_HEADER.search(c)}
                continue
            if in_scen and prob_cols:
                for j in prob_cols:
                    if j < len(cells) and re.search(r"\d\s*%", cells[j]):
                        cells[j] = " — "
                        stripped += 1
                new = "| " + " | ".join(c.strip() for c in cells) + " |"
            lines[i] = new
            continue
        prob_cols = set()
        new, n = _PROB_PHRASE.subn("", new)
        stripped += n
        new, n = _PROB_AFTER.subn("", new)
        stripped += n
        if in_scen:
            new, n = _RANGE_RE.subn("", new)
            stripped += n
            new, n = _strip_title_pct(new)
            stripped += n
        if new != line:
            lines[i] = _clean(new)
    return _tidy("\n".join(lines)) if stripped else md, stripped
