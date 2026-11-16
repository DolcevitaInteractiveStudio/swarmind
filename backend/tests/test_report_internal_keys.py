"""No internal snake_case key in a published report: conviction buckets, debate readings and the like are always
written with the reader labels of the report language. The methodological appendix keeps the raw field names.

Fictional report text. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_internal_keys.py
"""
import os
import re

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app.core.i18n import SUPPORTED_LANGUAGES, t, t_value
from app.report import postprocess
from app.report.report_agent import ReportAgent, SimulationToolExecutor
from app.simulation.engine import SimulationState

SNAKE_CASE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


def snake_case_outside_appendix(md: str, lang: str) -> list[str]:
    """The snake_case names a reader would see: everything before the methodological appendix."""
    heading = f"## {t(lang, 'report.headings.appendix')}"
    body = md.split(heading)[0]
    return SNAKE_CASE.findall(body)


MODEL_REPORT = {
    "en": """# Narrative Stress-Test Report: a fictional e-bike

## Executive Summary

The debate stayed open.

## Opinion Landscape

Most agents sit in conviction_very_high and a few in `conviction_low`.
- conviction_medium: 3 agents.
One rider is critical_neutral about the price.

## Debate Dynamics

The table reads polarization_active and parallel_silos, with insufficient_data for diversity.
The stance_shift_share stayed small.

## Methodological Appendix

The raw field opinion_strength is the conviction.
""",
    "it": """# Report di stress-test: una bici elettrica immaginaria

## Sintesi Esecutiva

Il dibattito è rimasto aperto.

## Panorama delle Opinioni

La maggior parte degli agenti è in convinzione_molto_alta e alcuni in conviction_very_high.
- convinzione_bassa: 3 agenti.

## Dinamiche del Dibattito

La tabella indica gradual_convergence e echo_chamber_strong.

## Appendice Metodologica

Il campo opinion_strength è la convinzione.
""",
}


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_catalog_labels_given_to_the_model_are_not_keys(lang):
    """The bucket labels go into the observations and the system prompt: the model copies them verbatim."""
    for key in ("report.conviction_buckets", "debate.labels"):
        for label in t_value(lang, key).values():
            assert not SNAKE_CASE.search(label), f"{lang} {key}: {label}"


def test_opinion_distribution_and_debate_block_show_labels_only():
    agents = [{"agent_id": f"a{i}", "name": f"Agente {i}", "role": "rider", "posts_made": 1,
               "opinion_strength": s, "emotional_state": "curious"} for i, s in enumerate((0.1, 0.5, 0.95))]
    state = SimulationState(simulation_id="sim-keys", project_id="p", topic="Bici", agents=agents)
    for lang in SUPPORTED_LANGUAGES:
        observation = SimulationToolExecutor(state, lang)._get_opinion_distribution()
        assert not any(SNAKE_CASE.search(k) for k in observation["conviction_buckets"])
    block = ReportAgent._format_debate_metrics({
        "polarization_delta": {"interpretation": "polarization_active", "delta": 0.2},
        "echo_chamber_index": {"score": 0.8, "interpretation": "echo_chamber_strong"},
        "information_diversity": {"interpretation": "stable_diversity"}}, "en")
    assert "[More polarized conviction]" in block and "polarization_active" not in block
    assert "echo_chamber_strong" not in block and "stable_diversity" not in block


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_a_published_report_has_no_snake_case_keys(lang):
    out = ReportAgent._finalize_report(MODEL_REPORT[lang], share_disclosure="", debate_block="",
                                       template_id=None, archetypes_limitation="", lang=lang)
    assert snake_case_outside_appendix(out, lang) == []
    buckets = t_value(lang, "report.conviction_buckets")
    assert buckets["very_high"] in out.lower() and buckets["low"] in out.lower()
    # The appendix keeps the raw field names
    assert "opinion_strength" in out.split(t(lang, "report.headings.appendix"))[1]


def test_known_keys_get_their_label_and_unknown_ones_become_words():
    md = "## Debate Dynamics\n\nPolarization: polarization_active. Rapid_x aside, the stance_shift_share is low.\n"
    out, keys = postprocess.localize_internal_keys(md, "en")
    assert keys == ["polarization_active"] and "more polarized conviction" in out
    out, names = postprocess.humanize_snake_case(out)
    assert names == ["stance_shift_share"] and "the stance shift share is low" in out
    # At the start of a sentence the label takes the capital
    start, _ = postprocess.localize_internal_keys("conviction_very_high is the largest bucket.", "en")
    assert start.startswith("Very high conviction is")


def test_links_code_and_appendix_keep_their_names():
    md = ("See https://example.test/a_b_c for details.\n\n```\nmean_opinion_strength = 0.4\n```\n\n"
          "## Methodological Appendix\n\nopinion_entropy is computed on conviction_very_high agents too.\n")
    assert postprocess.humanize_snake_case(md) == (md, [])
    assert postprocess.localize_internal_keys(md, "en") == (md, [])
