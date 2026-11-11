"""No internal names in the report: excluded archetypes, template ids, configuration keys, sampling methods.

The methodology appendix states the same facts in plain language (code-owned sentences), and explains the
two different caps: share of critical AGENTS vs share of critical POSTS.
Fictional data only. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_internal_names.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app.report import postprocess
from app.report.report_agent import ReportAgent
from app.templates import get_registry

STATS = {"adversarial_agents": 2, "total_agents": 17, "posts": 50, "adversarial_posts": 10, "share": 0.2, "cap": 0.25}
TRUNCATION = {"original_count": 3, "kept_count": 2, "max_share": 0.15, "num_agents": 17, "method": "random_sample",
              "excluded": ["Competitor indiretto in ascolto"]}
FORBIDDEN = ("random_sample", "max_adversarial_share", "max_share", "is_adversarial", "product_launch",
             "Competitor indiretto")


def test_disclosure_states_the_facts_in_plain_language_it():
    text = postprocess.critical_voices_disclosure(STATS, "it", agent_cap=0.15, truncation=TRUNCATION)
    assert ("Erano previste 3 voci critiche; ne sono state tenute 2 per rispettare la quota massima di voci "
            "critiche (15% degli agenti); quella esclusa è stata scelta a caso.") in text
    # the two caps, kept apart
    assert "al massimo il 15% degli agenti" in text and "al massimo il 25% dei post" in text
    assert "quota di agenti" in text and "quota di post" in text
    for word in FORBIDDEN:
        assert word not in text


def test_disclosure_states_the_facts_in_plain_language_en():
    text = postprocess.critical_voices_disclosure(STATS, "en", agent_cap=0.15, truncation=TRUNCATION)
    assert ("3 critical voices were planned; 2 were kept to respect the maximum share of critical voices "
            "(15% of the agents); the excluded one was chosen at random.") in text
    assert "at most 15% of the agents" in text and "at most 25% of the posts" in text


def test_disclosure_without_critical_voices_has_no_caps():
    text = postprocess.critical_voices_disclosure({**STATS, "adversarial_agents": 0}, "en", agent_cap=None)
    assert "0%" in text and "Two different limits" not in text


def test_disclosure_many_excluded():
    trunc = {**TRUNCATION, "original_count": 5, "kept_count": 1}
    text = postprocess.critical_voices_disclosure(STATS, "it", agent_cap=0.15, truncation=trunc)
    assert "ne è stata tenuta 1" in text and "le 4 escluse sono state scelte a caso" in text


@pytest.mark.parametrize("text, names, expected", [
    ("Le voci critiche (A, B, C) devono pesare", ["C"], "Le voci critiche (A, B) devono pesare"),
    ("Le voci critiche (A, B, C) devono pesare", ["a", "B", "C"], "Le voci critiche devono pesare"),
    ("la voce degli utenti (Utente long-tail, maggioranza silenziosa) e", ["Utente long-tail"],
     "la voce degli utenti (maggioranza silenziosa) e"),
    ("Nessun nome (A, B) da togliere", [], "Nessun nome (A, B) da togliere"),
])
def test_drop_names(text, names, expected):
    assert postprocess.drop_names(text, names) == expected


def test_template_instructions_never_name_an_excluded_archetype():
    tpl = get_registry().get("product_launch", "it")
    extra = tpl["report_focus"]["extra_instructions"]
    names = {p["key"]: p["name"] for p in tpl["adversarial_personas"]}
    assert names["indirect_competitor"] in extra
    cleaned = postprocess.drop_names(extra, [names["indirect_competitor"]])
    assert names["indirect_competitor"] not in cleaned
    assert names["jaded_early_adopter"] in cleaned and names["tech_journalist"] in cleaned


def test_template_info_gives_the_reader_name():
    info = ReportAgent._template_info("product_launch", "it")
    assert info["name"] == "Prelaunch feedback e obiezioni"
    assert "product_launch" in info["all_ids"] and info["agent_cap"] == 0.15
    assert "Competitor indiretto in ascolto" in info["persona_names"]


REPORT = """# Report

## Sintesi

La discussione resta aperta. La voce del Competitor indiretto in ascolto non era presente nella simulazione. \
Il prezzo è il tema centrale.

## Analisi Competitiva

- Il template product_launch prevede tre archetipi critici.
- Gli early adopter chiedono prove concrete.

| Parametro | Valore |
|---|---|
| tetto | max_adversarial_share |

## Appendice Metodologica

**Voci critiche:**
Le voci critiche sono agenti inseriti deliberatamente dal sistema. Il campionamento random_sample ha escluso una voce \
(max_adversarial_share=0.15).
"""


def test_strip_internal_names_removes_the_sentences_only():
    terms = [*postprocess.INTERNAL_KEYS, "product_launch", "Competitor indiretto in ascolto"]
    out, found = postprocess.strip_internal_names(REPORT, terms)
    assert "Competitor indiretto" not in out and "product_launch" not in out and "random_sample" not in out
    assert "La discussione resta aperta. Il prezzo è il tema centrale." in out
    assert "- Gli early adopter chiedono prove concrete." in out
    assert "| tetto | max_adversarial_share |" in out           # tables are left alone
    assert "Le voci critiche sono agenti inseriti deliberatamente dal sistema." in out
    assert {f["term"] for f in found} >= {"product_launch", "random_sample", "Competitor indiretto in ascolto"}


def test_finalize_report_has_no_internal_names_and_the_plain_disclosure():
    disclosure = postprocess.critical_voices_disclosure(STATS, "it", agent_cap=0.15, truncation=TRUNCATION)
    terms = [*postprocess.INTERNAL_KEYS, "product_launch", "Competitor indiretto in ascolto"]
    out = ReportAgent._finalize_report(
        REPORT.replace("| tetto | max_adversarial_share |\n", "| tetto | 15% |\n"),
        share_disclosure=disclosure, debate_block="", template_id="product_launch",
        archetypes_limitation="", lang="it", internal_terms=terms)
    body = out.split("## Appendice Metodologica")[0]
    for word in FORBIDDEN:
        assert word not in body
    appendix = out.split("## Appendice Metodologica")[1]
    assert "random_sample" not in appendix and "max_adversarial_share" not in appendix
    assert appendix.count("Erano previste 3 voci critiche") == 1
