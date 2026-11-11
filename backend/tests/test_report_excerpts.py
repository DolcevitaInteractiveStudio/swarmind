"""Excerpts of posts never end mid-word, and the report never quotes a post cut mid-word.

Fictional posts and reports only. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_excerpts.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import re

import pytest

from app.memory.knowledge_base import trim_kb_excerpt
from app.report import postprocess
from app.report.report_agent import ReportAgent
from app.utils.excerpt import ELLIPSIS, trim_excerpt

LONG_POST = ("Lavoro da casa tre giorni a settimana e il nuovo abbonamento mi incuriosisce. "
             "Prima di pagare vorrei dati chiari sul consumo reale della batteria, perché le promesse "
             "dei volantini non bastano più a nessuno di noi che compriamo online ogni mese.")


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text))


@pytest.mark.parametrize("cap", [40, 75, 120, 160, 200, 230])
def test_trim_excerpt_never_cuts_a_word(cap):
    excerpt = trim_excerpt(LONG_POST, cap)
    assert len(excerpt) <= cap
    body = excerpt.removesuffix(ELLIPSIS)
    # every word of the excerpt is a whole word of the post
    assert _words(body) <= _words(LONG_POST)
    assert LONG_POST.startswith(body)
    assert excerpt.endswith(ELLIPSIS) or excerpt.endswith(".")


def test_trim_excerpt_prefers_sentence_end_when_it_keeps_75_percent():
    first = LONG_POST.split(". ")[0] + "."
    cap = int(len(first) / 0.8)              # the sentence end keeps 80% of the limit
    assert trim_excerpt(LONG_POST, cap) == first
    cap = int(len(first) / 0.6)              # it would keep 60%: cut at a word instead
    assert trim_excerpt(LONG_POST, cap).endswith(ELLIPSIS)


def test_kb_excerpt_uses_the_same_cut():
    for cap in (50, 100, 150, 200):
        assert trim_kb_excerpt(LONG_POST, cap) == trim_excerpt(LONG_POST, cap)


def test_sample_posts_for_the_report_writer_end_on_a_whole_word():
    feed = [{"author_name": "Giulia Ferri", "content": LONG_POST}]
    block = ReportAgent._format_sample_posts(feed, n=5)
    content = block.split("]: ", 1)[1]
    assert "vorrei dat" not in content or "vorrei dati" in content
    body = content.removesuffix(ELLIPSIS)
    assert LONG_POST.startswith(body) and _words(body) <= _words(LONG_POST)


# ── Post-processing of quotes ────────────────────────────────────────────────

AGENT_TEXTS = [
    ("Giulia Ferri", "Lavoro da casa e vorrei dati chiari sulla batteria prima di pagare."),
    ("Marco Lodi", "Il prezzo mi sembra alto. Le fiere fanno vedere solo i modelli di punta."),
]


def test_quote_cut_mid_word_with_bracket_is_removed_with_its_sentence():
    md = ("## Analisi\n\nIl pubblico chiede trasparenza. Giulia Ferri scrive: \"Lavoro da casa e vorrei dat[...]\". "
          "Il tema torna spesso.")
    out, found = postprocess.fix_cut_quotes(md, AGENT_TEXTS)
    assert "dat[...]" not in out
    assert "Il pubblico chiede trasparenza. Il tema torna spesso." in out
    assert found == [{"action": "removed", "quote": "Lavoro da casa e vorrei dat[...]"}]


def test_quote_cut_mid_word_keeps_the_last_complete_sentence():
    md = "Marco Lodi osserva: «Il prezzo mi sembra alto. Le fiere f[...]» e chiude il thread."
    out, found = postprocess.fix_cut_quotes(md, AGENT_TEXTS)
    assert out.strip() == "Marco Lodi osserva: «Il prezzo mi sembra alto.» e chiude il thread."
    assert found[0]["action"] == "shortened"


def test_quote_cut_mid_word_detected_from_the_source_post():
    # plain ellipsis, no bracket: the post goes on with "fanno", so "f…" is a cut
    md = "- “Le fiere f…” — Marco Lodi (rivenditore)\n- Un'altra voce resta."
    out, _ = postprocess.fix_cut_quotes(md, AGENT_TEXTS)
    assert out.strip() == "- Un'altra voce resta."


@pytest.mark.parametrize("md", [
    "Giulia Ferri scrive: \"Lavoro da casa e vorrei dati chiari…\".",       # whole word, clean ellipsis
    "Marco Lodi: \"Il prezzo mi sembra alto.\"",                              # whole sentence
    "Si parla di \"[...] modelli di punta\" in apertura.",                    # elision at the start
    "| Voce | \"vorrei dat[...]\" |\n|---|---|",                               # tables are code-owned
    "## \"Le fiere f[...]\"",                                                  # headings stay
])
def test_whole_quotes_are_left_alone(md):
    out, found = postprocess.fix_cut_quotes(md, AGENT_TEXTS)
    assert out == md and found == []
