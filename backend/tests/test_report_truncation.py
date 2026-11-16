"""The whole report pipeline with a fake LLM that runs out of tokens: the published report is never cut silently.

A fake heavy model follows the ReACT loop, then writes the report in pieces: cut by the token limit
(finish_reason=length) with and without reasoning tokens, with a section left out, or never written. The report
must come out complete, or with the visible notice when a section cannot be obtained; in English and Italian.

Fictional product, agents and posts. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_truncation.py
"""
import asyncio
import os
import re

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
from structlog.testing import capture_logs

from app.core.i18n import t
from app.core.llm_response import LLMResponse
from app.report import completeness
from app.report.report_agent import ReportAgent
from app.simulation.engine import SimulationRound, SimulationState
from app.templates import get_registry

TEMPLATE = "product_launch"
TOPIC = "Velora Glide, a fictional folding e-bike"

TOOLS = ["compute_consensus", "get_opinion_distribution", "get_top_influencers", "get_emerging_topics",
         "query_feed", "interview_agent", "DONE"]

BODY = {
    "en": "The agents discussed the price and the battery range of the folding e-bike.",
    "it": "Gli agenti hanno discusso il prezzo e l'autonomia della bici elettrica pieghevole.",
}
CUT = {"en": "Most agents talk about the", "it": "La maggior parte degli agenti parla del"}  # a sentence cut short

SEGMENTS = [
    {"segment_id": "riders", "label": "Current Halden bike owners", "count": 5, "percentage": 50},
    {"segment_id": "shops", "label": "Partner bike shop owners and mechanics", "count": 4, "percentage": 40},
]


def _history(*stances):
    return [{"round": i, "stance": s} for i, s in enumerate(stances)]


def _state(lang: str) -> SimulationState:
    names = ["Marta Vello", "Ivo Sandri", "Nora Pelli", "Teo Bruni", "Lia Conte", "Ezio Marri", "Dora Fini",
             "Gino Tassi", "Rita Lodi"]
    stances = [("oppose", "oppose"), ("oppose", "oppose"), ("neutral", "oppose"), ("oppose", "oppose"),
               ("support", "support"), ("neutral", "support"), ("support", "support"), ("neutral", "neutral"),
               ("support", "support")]
    agents = []
    for i, (name, stance) in enumerate(zip(names, stances)):
        agents.append({
            "agent_id": f"a{i}", "name": name, "role": "rider" if i < 5 else "bike shop owner",
            "posts_made": 9 - i, "is_adversarial": False, "opinion_strength": 0.5 + i * 0.05,
            "emotional_state": "curious", "current_opinion": "The price matters more than the design.",
            "entity_id": "segment:riders" if i < 5 else "segment:shops", "stance": stance[-1],
            "stance_history": _history(*stance),
        })
    agents.append({"agent_id": "c1", "name": "Sara Critica", "role": "skeptical reviewer", "posts_made": 6,
                   "is_adversarial": True, "opinion_strength": 0.9, "emotional_state": "skeptical",
                   "stance": "oppose", "stance_history": _history("oppose", "oppose")})
    feed = [{"author_id": f"a{i % 9}", "author_name": names[i % 9], "round": i,
             "content": f"Post {i}: the battery range of the e-bike decides the price for commuters."}
            for i in range(12)]
    state = SimulationState(simulation_id="sim-trunc-test", project_id="p-test", topic=TOPIC, agents=agents,
                            social_feed=feed, current_round=6, language=lang)
    state.rounds = [SimulationRound(round_num=r, opinion_entropy=0.5, polarization_score=0.3) for r in range(6)]
    state.response_stats["posted"] = 60
    return state


def _sections(lang: str) -> list:
    names = get_registry().get(TEMPLATE, lang)["report_focus"]["mandatory_sections"]
    return completeness.report_sections(names, lang)


def _section_md(section, lang: str) -> str:
    return f"## {section.title}\n\n{BODY[lang]}\n"


def full_report(lang: str, skip: tuple = ()) -> str:
    title = f"# {t(lang, 'report.headings.title')}: {TOPIC}\n\n"
    return title + "\n".join(_section_md(s, lang) for s in _sections(lang) if s.key not in skip)


def sections_md(lang: str, keys) -> str:
    return "\n".join(_section_md(s, lang) for s in _sections(lang) if s.key in keys)


class FakeHeavyModel:
    """Follows the tool sequence, then answers the report requests from scripted queues.

    report: replies to "write the report" (and to the retry with a larger budget, same request);
    continue_: replies to "continue where you stopped"; missing: replies to "these sections are missing".
    """

    def __init__(self, report, continue_=(), missing=()):
        self.queues = {"report": list(report), "continue": list(continue_), "missing": list(missing)}
        self.tool = 0
        self.calls = []

    async def complete(self, messages, **kwargs):
        last = messages[-1]["content"]
        kind = ("continue" if "cut off by the length limit" in last
                else "missing" if "sections of the report are missing" in last
                else "report" if "Now write the complete prediction report" in last
                or "maximum number of tool calls" in last
                else "step")
        self.calls.append({"kind": kind, "max_tokens": kwargs.get("max_tokens"),
                           "reasoning_effort": kwargs.get("reasoning_effort")})
        if kind == "step":
            tool = TOOLS[min(self.tool, len(TOOLS) - 1)]
            self.tool += 1
            args = {"query_feed": ', "filter": "price"', "interview_agent": ', "agent_id": "a0"',
                    "get_top_influencers": ', "n": 5', "get_emerging_topics": ', "n": 8'}.get(tool, "")
            return LLMResponse(f'THOUGHT: next step.\nACTION: {{"tool": "{tool}"{args}}}', finish_reason="stop")
        queue = self.queues[kind]
        assert queue, f"unexpected {kind} request"
        return queue.pop(0)


def _generate(lang: str, model: FakeHeavyModel, monkeypatch):
    def template_metadata(self, simulation_id, lang=lang):
        names = get_registry().get(TEMPLATE, lang)["report_focus"]["mandatory_sections"]
        return self._sections_markdown(names, TEMPLATE, lang), "", TEMPLATE, names

    monkeypatch.setattr(ReportAgent, "_load_template_metadata", template_metadata)
    agent = ReportAgent(llm=model, max_tokens=2048, reasoning_effort="low")
    spec = {"domain_summary": "Commuters and bike shops judge a fictional folding e-bike.",
            "rationale": "Riders and shops react differently to the price.", "segments": SEGMENTS}
    with capture_logs() as logs:
        result = asyncio.run(agent.generate(_state(lang), "How will riders react to the launch price?",
                                            population_spec=spec, language=lang,
                                            brief_text="Velora Glide is a fictional folding e-bike."))
    return result, logs


def _headings(md: str) -> list[str]:
    return [line[3:].strip() for line in md.split("\n") if line.startswith("## ")]


def _assert_complete(result, lang: str):
    md = result.report_markdown
    assert completeness.missing_sections(md, _sections(lang)) == []
    assert result.missing_sections == []
    notice_head = t(lang, "report.incomplete.notice").split("{")[0].strip()
    assert notice_head not in md
    # The sections are in the order of the report format, each once
    order = [completeness._section_of(h, _sections(lang)) for h in _headings(md)]
    known = [i for i in order if i is not None]
    assert known == sorted(known) and len(known) == len(set(known))


@pytest.mark.parametrize("lang", ["en", "it"])
@pytest.mark.parametrize("reasoning_tokens", [1322, None], ids=["with_reasoning", "without_reasoning"])
def test_a_cut_report_is_continued(lang, reasoning_tokens, monkeypatch):
    whole = full_report(lang)
    landscape = completeness.report_sections([], lang)[2].title
    # Cut inside the first sentence of the opinion landscape, as in production; the continuation picks it up
    cut_at = whole.index(f"## {landscape}") + len(f"## {landscape}\n\n") + 20
    model = FakeHeavyModel(
        report=[LLMResponse(whole[:cut_at], finish_reason="length", completion_tokens=2048,
                            reasoning_tokens=reasoning_tokens)],
        continue_=[LLMResponse(whole[cut_at:], finish_reason="stop")])
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    assert BODY[lang] in result.report_markdown.split(f"## {landscape}")[1]
    assert [c["kind"] for c in model.calls if c["kind"] != "step"] == ["report", "continue"]
    assert any(e["event"] == "report_llm_truncated" and e["action"] == "continue" for e in logs)
    assert not any(e["event"] == "report_incomplete" for e in logs)


@pytest.mark.parametrize("lang", ["en", "it"])
def test_a_reply_spent_on_reasoning_is_asked_again_with_a_larger_budget(lang, monkeypatch):
    model = FakeHeavyModel(report=[LLMResponse("", finish_reason="length", completion_tokens=2048,
                                               reasoning_tokens=2048),
                                   LLMResponse(full_report(lang), finish_reason="stop", reasoning_tokens=900)])
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    budgets = [c["max_tokens"] for c in model.calls if c["kind"] == "report"]
    assert budgets == [2048, 4096]
    # Every call carries the report effort
    assert {c["reasoning_effort"] for c in model.calls} == {"low"}
    assert any(e["event"] == "report_llm_truncated" and e["action"] == "retry_larger_budget" for e in logs)


@pytest.mark.parametrize("lang", ["en", "it"])
def test_missing_sections_are_regenerated_in_place(lang, monkeypatch):
    skip = ("emerging_narratives", "positioning_risks", "prediction")
    model = FakeHeavyModel(report=[LLMResponse(full_report(lang, skip=skip), finish_reason="stop")],
                           missing=[LLMResponse(sections_md(lang, skip), finish_reason="stop")])
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    asked = [e for e in logs if e["event"] == "report_sections_missing"]
    assert asked and asked[0]["sections"] == list(skip)


@pytest.mark.parametrize("lang", ["en", "it"])
def test_a_report_still_cut_after_the_continuations_loses_the_partial_section_and_gets_it_back(lang, monkeypatch):
    whole = full_report(lang)
    confidence = [s for s in _sections(lang) if s.key == "confidence_assessment"][0].title
    head = whole[:whole.index(f"## {confidence}")] + f"## {confidence}\n\n{CUT[lang]}"
    model = FakeHeavyModel(
        report=[LLMResponse(head, finish_reason="length", reasoning_tokens=500)],
        continue_=[LLMResponse(" ...", finish_reason="length") for _ in range(ReportAgent.MAX_CONTINUATIONS)],
        missing=[LLMResponse(sections_md(lang, ("confidence_assessment", "appendix")), finish_reason="stop")])
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    assert CUT[lang] not in result.report_markdown
    assert any(e["event"] == "report_truncated_section_dropped" and e["section"] == confidence for e in logs)


@pytest.mark.parametrize("lang", ["en", "it"])
def test_a_section_never_written_gives_a_visible_notice_and_a_warning(lang, monkeypatch):
    skip = ("emerging_narratives", "messaging_gaps")
    never = LLMResponse(sections_md(lang, ("scenario_analysis",)), finish_reason="stop")  # a repeat, nothing new
    model = FakeHeavyModel(report=[LLMResponse(full_report(lang, skip=skip), finish_reason="stop")],
                           missing=[never] * ReportAgent.SECTION_RETRIES)
    result, logs = _generate(lang, model, monkeypatch)
    md = result.report_markdown
    titles = {s.key: s.title for s in _sections(lang)}
    notice = t(lang, "report.incomplete.notice", sections=f"{titles['emerging_narratives']}, {titles['messaging_gaps']}")
    lines = md.split("\n")
    assert lines[0].startswith("# ") and notice in lines[1:4]
    assert result.missing_sections == ["emerging_narratives", "messaging_gaps"]
    warning = [e for e in logs if e["event"] == "report_incomplete"]
    assert warning and warning[0]["missing_sections"] == ["emerging_narratives", "messaging_gaps"]
    assert warning[0]["log_level"] == "warning"


@pytest.mark.parametrize("lang", ["en", "it"])
def test_the_appendix_is_written_by_the_code_when_the_model_never_does(lang, monkeypatch):
    model = FakeHeavyModel(report=[LLMResponse(full_report(lang, skip=("appendix",)), finish_reason="stop")],
                           missing=[LLMResponse("", finish_reason="stop")] * ReportAgent.SECTION_RETRIES)
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    assert t(lang, "report.parameters.heading") in result.report_markdown
    assert any(e["event"] == "report_appendix_added" for e in logs)


# The opinion landscape of the production incident: stance per segment (the figures match the fictional run:
# riders 4 oppose / 1 support, shops 3 support / 1 neutral) and a raw conviction bucket key
LANDSCAPE = {
    "en": ("- Current Halden bike owners: 80.0% oppose and 20.0% support.\n"
           "- Partner bike shop owners and mechanics: 75.0% support and 25.0% neutral.\n"
           "- Several agents sit in conviction_very_high."),
    "it": ("- Current Halden bike owners: 80,0% contrari e 20,0% a favore.\n"
           "- Partner bike shop owners and mechanics: 75,0% a favore e 25,0% neutrali.\n"
           "- Diversi agenti sono in convinzione_molto_alta."),
}


@pytest.mark.parametrize("lang", ["en", "it"])
def test_production_replay_gives_a_complete_report_with_labels_and_both_segments(lang, monkeypatch):
    """Simulation 0ecf6547 in miniature: the reply stops inside the opinion landscape with the reasoning tokens
    spent, and the continuations do not finish it. The partial landscape is dropped and the missing sections are
    asked again: the report is complete, no raw key, both segment sentences kept, no hole in the list."""
    sections = _sections(lang)
    landscape = [s for s in sections if s.key == "opinion_landscape"][0]
    whole = full_report(lang).replace(f"## {landscape.title}\n\n{BODY[lang]}",
                                      f"## {landscape.title}\n\n{LANDSCAPE[lang]}")
    cut_at = whole.index(LANDSCAPE[lang]) + len(LANDSCAPE[lang])
    rest_keys = [s.key for s in sections[[s.key for s in sections].index("opinion_landscape"):]]
    model = FakeHeavyModel(
        report=[LLMResponse(whole[:cut_at], finish_reason="length", completion_tokens=2048, reasoning_tokens=1322)],
        continue_=[LLMResponse("", finish_reason="length", reasoning_tokens=2048)] * ReportAgent.MAX_CONTINUATIONS,
        missing=[LLMResponse(sections_md(lang, rest_keys).replace(
            f"## {landscape.title}\n\n{BODY[lang]}", f"## {landscape.title}\n\n{LANDSCAPE[lang]}"),
            finish_reason="stop")])
    result, logs = _generate(lang, model, monkeypatch)
    _assert_complete(result, lang)
    md = result.report_markdown
    appendix = md.index(f"## {t(lang, 'report.headings.appendix')}")
    assert not re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", md[:appendix])
    assert t(lang, "report.conviction_buckets.very_high") in md
    for line in LANDSCAPE[lang].split("\n")[:2]:
        assert line in md
    assert not any(e["event"] == "report_segment_stance_removed" for e in logs)
    # No empty bullet and no blank line between two bullets
    assert not re.search(r"^\s*[-*]\s*$", md, re.M)
    assert not re.search(r"^- .*\n\n- ", md, re.M)
