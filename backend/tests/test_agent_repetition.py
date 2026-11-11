"""An agent never publishes the same post twice: one retry asking for something new, then the post is skipped.

Fictional personas and posts, fake LLM and memory. No network, no Redis, no Chroma.
Usage: cd backend && python -m pytest tests/test_agent_repetition.py
"""
import asyncio
import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from types import SimpleNamespace

import pytest

from app.agents.agent import REPETITION_RETRY, Agent, AgentPersona
from app.agents.repetition import REPETITION_THRESHOLD, jaccard, repeats
from app.simulation.engine import REPETITION_RETRIES, SimulationEngine, SimulationState

FIRST = ("Un abbonamento a 19 euro al mese per un'app di contabilità è troppo per chi fattura poco: "
         "prima voglio vedere una prova gratuita seria, non i soliti sette giorni.")
REWORDED = ("Un abbonamento da 19 euro al mese per un'app di contabilità è troppo per chi fattura poco: "
            "prima voglio una prova gratuita seria, non i soliti sette giorni!")
NEW = ("Chi segue la contabilità di un piccolo studio guarda all'esportazione verso il commercialista: "
       "se manca, il prezzo diventa secondario.")
SAME_TOPIC = ("Ho provato l'app per la contabilità: l'interfaccia è chiara, ma il prezzo mensile pesa per "
              "un libero professionista che inizia adesso.")


def test_similarity_separates_a_copy_from_a_new_post():
    assert jaccard(FIRST, REWORDED) >= REPETITION_THRESHOLD
    assert jaccard(FIRST, NEW) < REPETITION_THRESHOLD
    assert jaccard(FIRST, SAME_TOPIC) < REPETITION_THRESHOLD
    assert repeats(REWORDED, [NEW, FIRST]) == FIRST
    assert repeats(NEW, [FIRST]) is None and repeats(FIRST, []) is None


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return json.dumps(self.replies.pop(0))


class FakeMemory:
    async def get_recent(self, n=5):
        return []

    async def store(self, content, metadata=None):
        return None


def _post(content, action="CREATE_POST"):
    return {"action": action, "content": content, "target_post_id": None, "reasoning": "",
            "opinion_shift": 0.0, "emotional_shift": None, "target_agent": None}


def _agent(llm):
    persona = AgentPersona(name="Marta Galli", role="libera professionista", background="Apre la partita IVA.",
                           personality={}, core_beliefs=["Il prezzo conta"], motivations=[], fears=[],
                           communication_style="direct", initial_opinion="Dubbiosa", opinion_strength=0.6,
                           emotional_state="skeptical")
    agent = Agent(agent_id="a1", entity_id="e1", entity_type="PERSON", persona=persona, memory=FakeMemory(),
                  simulation_id="sim-test", language="it", _llm=llm)
    agent.recent_posts = [FIRST]
    agent.posts_made = 1
    return agent


def _decide(agent):
    return asyncio.run(agent.decide_action("contesto", ["CREATE_POST", "LIKE", "DO_NOTHING"], [], round_num=5))


def test_repeated_post_is_retried_once_and_the_new_one_published():
    llm = FakeLLM([_post(REWORDED), _post(NEW)])
    agent = _agent(llm)
    result = _decide(agent)
    assert result["content"] == NEW and result["repetition"] == "retried"
    assert len(llm.calls) == 2
    retry_turn = llm.calls[1][-1]["content"]
    assert retry_turn.startswith(REPETITION_RETRY.split("\n")[0]) and FIRST[:40] in retry_turn
    assert agent.recent_posts == [FIRST, NEW] and agent.posts_made == 2


def test_post_repeated_again_after_the_retry_is_skipped():
    llm = FakeLLM([_post(REWORDED), _post(FIRST)])
    agent = _agent(llm)
    result = _decide(agent)
    assert result["action"] == "DO_NOTHING" and result["content"] == "" and result["repetition"] == "skipped"
    assert agent.recent_posts == [FIRST] and agent.posts_made == 1


def test_new_post_needs_no_retry():
    llm = FakeLLM([_post(NEW)])
    result = _decide(_agent(llm))
    assert result["repetition"] is None and len(llm.calls) == 1


def test_like_is_never_checked():
    llm = FakeLLM([{**_post(FIRST, "LIKE"), "target_post_id": "P1"}])
    result = _decide(_agent(llm))
    assert result["repetition"] is None and len(llm.calls) == 1


class ScriptedAgent(SimpleNamespace):
    async def decide_action(self, **kwargs):
        return self.result


def test_engine_counts_retries_and_skips(monkeypatch):
    def scripted(agent_id, result):
        return ScriptedAgent(agent_id=agent_id, persona=SimpleNamespace(name=agent_id, role="r"), is_adversarial=False,
                             opinion_strength=0.5, posts_made=0, result={"response_outcome": "ok", **result})
    agents = [
        scripted("a1", {"action": "CREATE_POST", "content": NEW, "repetition": "retried"}),
        scripted("a2", {"action": "DO_NOTHING", "content": "", "repetition": "skipped"}),
        scripted("a3", {"action": "CREATE_POST", "content": SAME_TOPIC, "repetition": None}),
    ]
    state = SimulationState(simulation_id="sim-test", project_id="p", topic="t", agents=agents)
    engine = SimulationEngine(redis_url="redis://localhost:1/0")

    async def no_kb(_state):
        return False
    monkeypatch.setattr(engine, "_open_kb", no_kb)
    monkeypatch.setattr(engine, "_sample_agents", lambda agents, n, slots: agents)
    monkeypatch.setattr(engine, "_build_env_context", lambda state, round_num: "")
    asyncio.run(engine._run_round(state, 1, 3, ["CREATE_POST", "DO_NOTHING"]))
    stats = state.response_stats
    assert stats["posted"] == 2 and stats["repetition_skipped"] == 1 and stats[REPETITION_RETRIES] == 2
    assert stats["do_nothing"] == 0
