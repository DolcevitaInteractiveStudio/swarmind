"""Writing rules of the report prompt: complete sentences, lists of agents, no internal names.

No network, no database.
Usage: cd backend && python -m pytest tests/test_report_prompt_rules.py
"""
import os
import re

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app.report.report_agent import ReportAgent


@pytest.mark.parametrize("lang", ["en", "it"])
def test_system_prompt_has_the_writing_rules(lang):
    prompt = ReportAgent._system_prompt(lang, topic="Abbonamento di prova", template_id=None,
                                        archetypes_limitation="", dynamic_sections="", extra_instructions="")
    assert "24. COMPLETE SENTENCES." in prompt and "A conditional always has its consequence" in prompt
    assert "25. LISTS OF AGENTS." in prompt and "the name first, then the role in brackets" in prompt
    assert "23. NO INTERNAL NAMES." in prompt
    # every placeholder of the rules was filled
    assert not re.search(r"\{H_[A-Z_]+\}", prompt)


def test_rule_numbers_are_unique_after_the_new_rules():
    prompt = ReportAgent._system_prompt("en", topic="t", template_id=None, archetypes_limitation="",
                                        dynamic_sections="", extra_instructions="")
    numbers = re.findall(r"^(2[2-5])\. [A-Z]", prompt, re.M)
    assert numbers == ["22", "23", "24", "25"]
