"""Top influencers are natural agents only: critical voices post as often as the system makes them.

Fictional agents and posts. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_influencers.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from app.report.report_agent import ReportAgent, SimulationToolExecutor, top3_share
from app.simulation.engine import SimulationState


def _agent(agent_id, name, posts, adversarial=False):
    return {"agent_id": agent_id, "name": name, "role": "critico" if adversarial else "cliente", "posts_made": posts,
            "is_adversarial": adversarial, "opinion_strength": 0.6, "emotional_state": "curious"}


def _state():
    agents = [
        _agent("c1", "Voce critica Uno", 9, adversarial=True),
        _agent("c2", "Voce critica Due", 8, adversarial=True),
        _agent("n1", "Elena Sarti", 7),
        _agent("n2", "Paolo Greco", 5),
        _agent("n3", "Irene Volpe", 4),
        _agent("n4", "Luca Neri", 2),
    ]
    state = SimulationState(simulation_id="sim-test", project_id="p", topic="Abbonamento di prova", agents=agents)
    state.response_stats["posted"] = 35
    return state


def test_top_influencers_rank_natural_agents_only():
    result = SimulationToolExecutor(_state(), "it")._get_top_influencers(3)
    assert [a["name"] for a in result["top_influencers"]] == ["Elena Sarti", "Paolo Greco", "Irene Volpe"]
    assert [(v["name"], v["posts"]) for v in result["critical_voices"]] == [("Voce critica Uno", 9),
                                                                            ("Voce critica Due", 8)]
    assert "natural agents only" in result["note"]


def test_top3_share_counts_natural_agents_and_critical_posts_apart():
    top3 = top3_share(_state())
    assert top3["top_posts"] == 16 and top3["total_posts"] == 35 and top3["critical_posts"] == 17
    assert round(top3["share"] + top3["critical_share"] + top3["rest_share"], 6) == 1


def test_appendix_sentence_names_critical_posts_separately():
    top3 = top3_share(_state())
    it = ReportAgent._appendix("it", None, "", top3)
    assert ("I 3 agenti naturali più attivi hanno pubblicato il 45,7% dei post (16 su 35); le voci critiche ne "
            "hanno pubblicati 17 (48,6%), con una frequenza stabilita dal sistema; il restante 5,7% viene dagli "
            "altri agenti naturali.") in it
    en = ReportAgent._appendix("en", None, "", top3)
    assert "The 3 most active natural agents account for 45.7% of the posts published (16 of 35)" in en
    assert "critical voices are not ranked" in en


def test_appendix_sentence_without_critical_voices():
    state = _state()
    state.agents = [a for a in state.agents if not a["is_adversarial"]]
    state.response_stats["posted"] = 18
    en = ReportAgent._appendix("en", None, "", top3_share(state))
    assert "account for 88.9% of the posts published (16 of 18); the remaining 11.1% comes from the agents not quoted" in en


def test_computed_numbers_include_the_new_shares():
    numbers = SimulationToolExecutor(_state(), "it").computed_numbers()
    assert {45.7, 48.6, 5.7, 17.0} <= numbers
