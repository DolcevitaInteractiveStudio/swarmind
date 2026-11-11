"""The fictional fixtures stay valid for the population CLIs (app.population.cli, persona_cli).

Usage: cd backend && python -m pytest tests/test_population_fixtures.py
"""
import json
import os
from pathlib import Path

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from app.agents.agent import AgentPersona
from app.population.demographer import PopulationSpec

FIXTURES = Path(__file__).parent / "fixtures"
CASE = "quillfern_pricing"


def _load(kind, ext="json"):
    return (FIXTURES / kind / f"{CASE}.{ext}").read_text(encoding="utf-8")


def test_brief_is_marked_fictional():
    brief = _load("briefs", "txt")
    assert brief.startswith("FICTIONAL TEST BRIEF")


def test_population_spec_round_trips_and_validates():
    data = json.loads(_load("population_specs"))
    spec = PopulationSpec.from_dict(data)
    assert spec.normalize()["changed"] is False
    assert spec.validate() == []
    assert spec.to_dict()["segments"] == data["segments"]


def test_agents_match_the_spec():
    spec = PopulationSpec.from_dict(json.loads(_load("population_specs")))
    data = json.loads(_load("agents"))
    segments = {s.segment_id: s.count for s in spec.segments}
    assert data["by_segment"] == segments
    assert data["agents_count"] == len(data["agents"]) == spec.total_agents
    for agent in data["agents"]:
        persona = AgentPersona(**agent["persona"])
        assert agent["entity_id"].removeprefix("segment:") in segments
        assert 0.0 <= persona.opinion_strength <= 1.0
        assert persona.background.startswith("Fictional persona.")
