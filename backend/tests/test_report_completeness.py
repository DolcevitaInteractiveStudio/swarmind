"""Report completeness: continuation of a reply cut by the token limit, required sections, the notice.

Fictional report text, fake LLM. No network. Usage: cd backend && python -m pytest tests/test_report_completeness.py
"""
import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from app.core.llm_response import LLMResponse
from app.report import completeness as c
from app.report.report_agent import ReportAgent

SECTIONS_EN = c.report_sections(["messaging_gaps", "positioning_risks"], "en")


def _report(*titles: str, body: str = "Text of the section.") -> str:
    parts = ["# Narrative Stress-Test Report: a fictional e-bike", ""]
    for title in titles:
        parts += [f"## {title}", "", body, ""]
    return "\n".join(parts)


ALL_EN = ["Executive Summary", "Simulation Metrics", "Opinion Landscape", "Emerging Narratives", "Agent Perspectives",
          "Launch Messaging Gaps", "Positioning Risks", "Debate Dynamics", "Scenario Analysis",
          "Most plausible reaction", "Confidence Assessment", "Methodological Appendix"]


def test_required_sections_follow_the_report_format():
    keys = [s.key for s in SECTIONS_EN]
    assert keys == ["executive_summary", "simulation_metrics", "opinion_landscape", "emerging_narratives",
                    "agent_perspectives", "messaging_gaps", "positioning_risks", "debate_dynamics",
                    "scenario_analysis", "prediction", "confidence_assessment", "appendix"]
    # The metrics table is the code's: never asked of the model
    assert [s.key for s in SECTIONS_EN if not s.required] == ["simulation_metrics"]


def test_a_complete_report_misses_nothing_and_numbered_bold_headings_count():
    assert c.missing_sections(_report(*ALL_EN), SECTIONS_EN) == []
    md = _report(*[f"{i}. **{title}**:" for i, title in enumerate(ALL_EN, start=1)])
    assert c.missing_sections(md, SECTIONS_EN) == []


def test_missing_sections_are_listed_in_report_order():
    md = _report("Executive Summary", "Simulation Metrics", "Opinion Landscape")
    missing = [s.key for s in c.missing_sections(md, SECTIONS_EN)]
    assert missing == ["emerging_narratives", "agent_perspectives", "messaging_gaps", "positioning_risks",
                       "debate_dynamics", "scenario_analysis", "prediction", "confidence_assessment", "appendix"]


def test_italian_headings_are_recognised():
    sections = c.report_sections(["messaging_gaps"], "it")
    md = _report("Sintesi Esecutiva", "Panorama delle Opinioni", "Narrative Emergenti", "Prospettive degli Agenti",
                 "Gap nel Messaggio di Lancio", "Dinamiche del Dibattito", "Analisi degli Scenari",
                 "Reazione più plausibile", "Valutazione della Confidenza", "Appendice Metodologica")
    assert c.missing_sections(md, sections) == []


def test_the_last_section_cut_short_is_dropped():
    md = _report("Executive Summary", "Opinion Landscape", body="Most agents sit in the very")
    out, dropped = c.drop_last_section(md)
    assert dropped == "Opinion Landscape"
    assert "## Opinion Landscape" not in out and "## Executive Summary" in out


def test_regenerated_sections_go_back_to_their_place():
    md = _report("Executive Summary", "Opinion Landscape", "Scenario Analysis", "Methodological Appendix")
    missing = c.missing_sections(md, SECTIONS_EN)
    addition = ("## Emerging Narratives\n\nTopic one.\n\n## Executive Summary\n\nA repeat, ignored.\n\n"
                "## Agent Perspectives\n\nOne agent.\n\n## Confidence Assessment\n\nLow.\n")
    out, added = c.merge_sections(md, addition, missing, SECTIONS_EN)
    assert added == ["emerging_narratives", "agent_perspectives", "confidence_assessment"]
    order = [line[3:] for line in out.split("\n") if line.startswith("## ")]
    assert order == ["Executive Summary", "Opinion Landscape", "Emerging Narratives", "Agent Perspectives",
                     "Scenario Analysis", "Confidence Assessment", "Methodological Appendix"]
    assert "A repeat, ignored." not in out


def test_appendix_is_added_by_the_code_only_when_missing():
    md = _report("Executive Summary")
    out, added = c.ensure_appendix(md, "**Simulation parameters:**\n- Agents: 12", "en")
    assert added and out.rstrip().endswith("- Agents: 12") and "## Methodological Appendix" in out
    again, added_again = c.ensure_appendix(out, "other", "en")
    assert not added_again and again == out


def test_continuation_joins_without_repeats():
    head = "## Opinion Landscape\n\nMost agents oppose the change because the price"
    assert c.join_continuation(head, " is too high.\n") == head + " is too high.\n"
    # The model repeated the end of what it wrote
    assert c.join_continuation(head, "oppose the change because the price is too high.") == (
        head + " is too high.")
    # The model restarted the section: the partial copy goes
    restarted = "## Opinion Landscape\n\nMost agents oppose the change.\n\n## Emerging Narratives\n\nPrice."
    assert c.join_continuation("# Title\n\n" + head, restarted) == "# Title\n\n" + restarted
    # A new section after a sentence that ended without a newline
    assert c.join_continuation("Last sentence.", "## Next\n\nText") == "Last sentence.\n\n## Next\n\nText"


def test_the_notice_sits_under_the_title_in_the_report_language():
    md = _report("Executive Summary")
    missing = [s for s in SECTIONS_EN if s.key in ("emerging_narratives", "prediction")]
    out = c.add_incomplete_notice(md, missing, "en")
    lines = out.split("\n")
    assert lines[0].startswith("# Narrative Stress-Test Report")
    assert lines[2] == ("> **Incomplete report.** These sections could not be generated within the token budget "
                        "of the model: Emerging Narratives, Most plausible reaction. The other sections are complete.")
    it_missing = [s for s in c.report_sections([], "it") if s.key == "agent_perspectives"]
    assert "**Report incompleto.**" in c.add_incomplete_notice(md, it_missing, "it")
    assert "Prospettive degli Agenti" in c.add_incomplete_notice(md, it_missing, "it")


class ScriptedLLM:
    """Replies in order; records the budget and the last message of every call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append({"max_tokens": kwargs.get("max_tokens"), "last": messages[-1]["content"],
                           "n": len(messages)})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_a_cut_reply_is_continued_until_it_ends():
    llm = ScriptedLLM([LLMResponse("## Opinion Landscape\n\nMost agents", finish_reason="length",
                                   reasoning_tokens=1322),
                       LLMResponse(" oppose the change.", finish_reason="length"),
                       LLMResponse("\n\n## Emerging Narratives\n\nPrice.", finish_reason="stop")])
    agent = ReportAgent(llm=llm, max_tokens=2048)
    out = asyncio.run(agent._call([{"role": "user", "content": "write"}], "en"))
    assert str(out) == "## Opinion Landscape\n\nMost agents oppose the change.\n\n## Emerging Narratives\n\nPrice."
    assert out.finish_reason == "stop"
    # The continuation is asked in the same conversation, after the partial reply
    assert "cut off by the length limit" in llm.calls[1]["last"] and llm.calls[1]["n"] == 3


def test_a_reply_with_reasoning_only_is_asked_again_with_twice_the_budget():
    llm = ScriptedLLM([LLMResponse("", finish_reason="length", reasoning_tokens=2048),
                       LLMResponse("THOUGHT: next.\nACTION: {\"tool\": \"compute_consensus\"}", finish_reason="stop")])
    agent = ReportAgent(llm=llm, max_tokens=2048)
    out = asyncio.run(agent._call([{"role": "user", "content": "go"}], "en", stop=["OBSERVATION:"]))
    assert "compute_consensus" in out and out.finish_reason == "stop"
    assert [call["max_tokens"] for call in llm.calls] == [2048, 4096]


def test_a_refused_larger_budget_returns_an_empty_cut_reply():
    error = Exception("max_tokens is too large for this model")
    llm = ScriptedLLM([LLMResponse("", finish_reason="length", reasoning_tokens=2048), error])
    out = asyncio.run(ReportAgent(llm=llm, max_tokens=2048)._call([{"role": "user", "content": "go"}], "en"))
    assert str(out) == "" and out.finish_reason == "length"


def test_continuations_stop_after_the_limit():
    replies = [LLMResponse(f"part {i} ", finish_reason="length") for i in range(1 + ReportAgent.MAX_CONTINUATIONS)]
    llm = ScriptedLLM(replies)
    out = asyncio.run(ReportAgent(llm=llm)._call([{"role": "user", "content": "go"}], "en"))
    assert out.finish_reason == "length" and len(llm.calls) == 1 + ReportAgent.MAX_CONTINUATIONS
