"""
Completeness of the report: the sections required by the REPORT FORMAT are all there.

A report call that ends on the token limit (finish_reason=length) is continued; a section that is still
missing, or the one cut short at the end, is asked again; if it still fails, the report is published with a
visible notice that lists the missing sections (report.incomplete.notice). Pure functions on the markdown:
the calls to the model are in report_agent.

Order of the sections (the REPORT FORMAT of report_agent): executive summary, simulation metrics, opinion
landscape, emerging narratives, agent perspectives, the template sections and debate_dynamics, scenarios,
most plausible reaction, confidence, methodological appendix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.i18n import DEFAULT_LANGUAGE, t
from .postprocess import (
    APPENDIX_HEADING_RE, CONFIDENCE_HEADING_RE, DEBATE_HEADING_RE, LANDSCAPE_HEADING_RE, PREDICTION_HEADING_RE,
    SCENARIO_HEADING_RE, SIM_METRICS_HEADING_RE, _catalog_alternatives,
)
from .sections import ALWAYS_SECTIONS, SECTION_DESCRIPTIONS, section_title

_LEVEL2 = re.compile(r"^##\s+(.*\S)\s*$")
_ANY_HEADING_LINE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")

# Sections the code writes or completes itself when the model leaves them out: the metrics table
# (ensure_metrics_table), the debate table (ensure_debate_section), the appendix (its text is the code's).
# They are asked again like the others, but never make the report "incomplete".
CODE_FALLBACK = ("simulation_metrics", "debate_dynamics", "appendix")


@dataclass(frozen=True)
class ReportSection:
    key: str
    title: str
    pattern: re.Pattern
    required: bool = True


def _catalog_heading_re(key: str) -> re.Pattern:
    return re.compile(_catalog_alternatives(key), re.I)


def report_sections(template_sections: list[str] | None, lang: str = DEFAULT_LANGUAGE) -> list[ReportSection]:
    """The sections of the report in their order, with the heading of the report language.
    The simulation metrics are not required from the model: the code inserts the table."""
    def core(key: str, pattern: re.Pattern | None = None, required: bool = True) -> ReportSection:
        return ReportSection(key, t(lang, f"report.headings.{key}"),
                             pattern or _catalog_heading_re(f"report.headings.{key}"), required)

    names = [n for n in dict.fromkeys([*(template_sections or []), *ALWAYS_SECTIONS]) if n in SECTION_DESCRIPTIONS]
    dynamic = [ReportSection(n, section_title(n, lang),
                             DEBATE_HEADING_RE if n == "debate_dynamics" else _catalog_heading_re(f"report.sections.{n}"))
               for n in names]
    return [
        core("executive_summary"),
        core("simulation_metrics", SIM_METRICS_HEADING_RE, required=False),
        core("opinion_landscape", LANDSCAPE_HEADING_RE),
        core("emerging_narratives"),
        core("agent_perspectives"),
        *dynamic,
        core("scenario_analysis", SCENARIO_HEADING_RE),
        core("prediction", PREDICTION_HEADING_RE),
        core("confidence_assessment", CONFIDENCE_HEADING_RE),
        core("appendix", APPENDIX_HEADING_RE),
    ]


def _heading_text(line: str) -> str | None:
    m = _LEVEL2.match(line)
    if not m:
        return None
    # "## 1. **Executive Summary**:" -> "Executive Summary"
    return re.sub(r"^\d+[.)]\s*", "", m.group(1).strip()).strip("*_: ").strip()


def _section_of(heading: str, sections: list[ReportSection]) -> int | None:
    """Index of the section a level-2 heading belongs to (the first in report order that matches)."""
    for i, section in enumerate(sections):
        if section.pattern.search(heading):
            return i
    return None


def present_sections(md: str, sections: list[ReportSection]) -> set[str]:
    found = set()
    for line in (md or "").split("\n"):
        heading = _heading_text(line)
        if heading is not None:
            i = _section_of(heading, sections)
            if i is not None:
                found.add(sections[i].key)
    return found


def missing_sections(md: str, sections: list[ReportSection]) -> list[ReportSection]:
    """The required sections without their heading, in report order."""
    present = present_sections(md, sections)
    return [s for s in sections if s.required and s.key not in present]


def drop_last_section(md: str) -> tuple[str, str | None]:
    """The report without its last level-2 section (cut short by the token limit): (report, its heading).
    Without a level-2 heading the report stays as it is."""
    lines = (md or "").split("\n")
    last = next((i for i in range(len(lines) - 1, -1, -1) if _LEVEL2.match(lines[i])), None)
    if last is None:
        return md, None
    heading = _heading_text(lines[last])
    return "\n".join(lines[:last]).rstrip() + "\n", heading


def _split_level2(md: str) -> list[tuple[str | None, list[str]]]:
    """[(heading text or None for the text before the first level-2 heading, lines)]."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in (md or "").split("\n"):
        heading = _heading_text(line)
        if heading is not None:
            blocks.append((heading, [line]))
        else:
            blocks[-1][1].append(line)
    return blocks


def merge_sections(md: str, addition: str, wanted: list[ReportSection],
                   sections: list[ReportSection]) -> tuple[str, list[str]]:
    """The sections of addition that the report lacks (wanted), each inserted at its place in the report
    order. Other sections of addition (repeats of sections already there) are ignored.
    Returns (report, keys of the sections inserted)."""
    wanted_keys = {s.key for s in wanted}
    index = {s.key: i for i, s in enumerate(sections)}
    new_blocks: dict[str, list[str]] = {}
    for heading, lines in _split_level2(addition)[1:]:
        i = _section_of(heading, sections)
        if i is None or sections[i].key not in wanted_keys or sections[i].key in new_blocks:
            continue
        body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        key = sections[i].key
        new_blocks[key] = [f"## {sections[i].title}", "", body, ""]
    if not new_blocks:
        return md, []
    blocks = _split_level2(md)
    for key in sorted(new_blocks, key=index.get):
        k = index[key]
        at = len(blocks)
        for j, (heading, _) in enumerate(blocks[1:], start=1):
            i = _section_of(heading, sections)
            if i is not None and i > k:
                at = j
                break
        if at == len(blocks) and blocks[-1][1] and blocks[-1][1][-1].strip():
            blocks[-1][1].append("")
        blocks.insert(at, (sections[k].title, new_blocks[key]))
    text = "\n".join("\n".join(lines) for _, lines in blocks)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n", sorted(new_blocks, key=index.get)


def ensure_appendix(md: str, appendix_text: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, bool]:
    """The methodological appendix is text of the code (catalog + run values): when the model never wrote it,
    the code appends it. Returns (report, added)."""
    if not md or not appendix_text or any(_heading_text(line) is not None
                                          and APPENDIX_HEADING_RE.search(_heading_text(line))
                                          for line in md.split("\n")):
        return md, False
    return md.rstrip() + f"\n\n## {t(lang, 'report.headings.appendix')}\n\n{appendix_text.strip()}\n", True


def join_continuation(head: str, tail: str) -> str:
    """head + the continuation of a reply cut by the token limit. The model sometimes repeats the end of head
    or restarts the section it was writing: the repeat is dropped, a restarted heading replaces the partial
    section."""
    head, tail = head or "", tail or ""
    if not tail.strip():
        return head
    first = next((line for line in tail.split("\n") if line.strip()), "")
    if _ANY_HEADING_LINE.match(first.strip()):
        lines = head.split("\n")
        restarted = [i for i, line in enumerate(lines) if line.strip() == first.strip()]
        if restarted:
            kept = "\n".join(lines[:restarted[-1]]).rstrip("\n")
            return (kept + "\n\n" if kept else "") + tail.lstrip("\n")
    for size in range(min(len(head), len(tail), 400), 19, -1):
        if head.endswith(tail[:size]):
            tail = tail[size:]
            break
    if _ANY_HEADING_LINE.match(tail.lstrip(" ").split("\n", 1)[0].strip()) and not head.endswith("\n"):
        return head.rstrip() + "\n\n" + tail.lstrip("\n")
    return head + tail


def incomplete_notice(missing: list[ReportSection], lang: str = DEFAULT_LANGUAGE) -> str:
    return t(lang, "report.incomplete.notice", sections=", ".join(s.title for s in missing))


def add_incomplete_notice(md: str, missing: list[ReportSection], lang: str = DEFAULT_LANGUAGE) -> str:
    """The notice right under the report title (at the top without a title)."""
    notice = incomplete_notice(missing, lang)
    lines = (md or "").split("\n")
    title = next((i for i, line in enumerate(lines) if re.match(r"^#\s", line)), None)
    at = title + 1 if title is not None else 0
    lines[at:at] = ["", notice, ""] if title is not None else [notice, ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"

