"""Heavy-tier budgets and reasoning: the effort sent to OpenRouter, what the log says, the report budget.

Fake provider calls, no network. Usage: cd backend && python -m pytest tests/test_llm_reasoning_budget.py
"""
import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from types import SimpleNamespace

from structlog.testing import capture_logs

from app.config import Config
from app.core import llm_router
from app.core.llm_response import LLMResponse
from app.core.llm_router import LLMConfig, MultiProviderLLM, reasoning_effort_setting
from app.report.report_agent import ReportAgent


class ProviderError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def _client(provider="openrouter"):
    return MultiProviderLLM(LLMConfig(provider=provider, api_key="test-key", model_heavy="vendor/heavy-model",
                                      model_agent="vendor/agent-model", model_fast="vendor/fast-model"))


def test_effort_setting_accepts_the_known_values_only():
    assert reasoning_effort_setting("LOW") == "low"
    assert reasoning_effort_setting(" xhigh ") == "xhigh"
    assert reasoning_effort_setting("default") is None
    assert reasoning_effort_setting("") is None
    assert reasoning_effort_setting("turbo") is None


def test_heavy_tier_on_openrouter_sends_the_configured_effort(monkeypatch):
    recorded = []

    async def fake_call(api_key, model, messages, temperature, max_tokens, json_mode, base_url=None,
                        stop=None, reasoning=None):
        recorded.append({"max_tokens": max_tokens, "reasoning": reasoning})
        return LLMResponse("ok", finish_reason="stop", completion_tokens=2, reasoning_tokens=40)

    monkeypatch.setattr(llm_router, "_call_openai_compatible", fake_call)
    monkeypatch.setattr(Config, "HEAVY_REASONING_EFFORT", "low")
    with capture_logs() as logs:
        result = asyncio.run(_client().complete([{"role": "user", "content": "x"}], tier="heavy", max_tokens=8000))
    assert recorded == [{"max_tokens": 8000, "reasoning": {"effort": "low"}}]
    assert result.reasoning_mode == "effort=low"
    ok = [e for e in logs if e["event"] == "llm_call_ok"][0]
    # The log says what was sent and what the model spent
    assert ok["reasoning_mode"] == "effort=low" and ok["max_tokens"] == 8000 and ok["reasoning_tokens"] == 40


def test_explicit_effort_wins_and_default_sends_nothing(monkeypatch):
    recorded = []

    async def fake_call(api_key, model, messages, temperature, max_tokens, json_mode, base_url=None,
                        stop=None, reasoning=None):
        recorded.append(reasoning)
        return LLMResponse("ok", finish_reason="stop")

    monkeypatch.setattr(llm_router, "_call_openai_compatible", fake_call)
    client = _client()
    medium = asyncio.run(client.complete([{"role": "user", "content": "x"}], tier="heavy", reasoning_effort="medium"))
    default = asyncio.run(client.complete([{"role": "user", "content": "x"}], tier="heavy",
                                          reasoning_effort="default"))
    assert recorded == [{"effort": "medium"}, None]
    assert medium.reasoning_mode == "effort=medium"
    assert default.reasoning_mode == "provider_default"


def test_agent_tier_sends_no_effort_unless_asked(monkeypatch):
    recorded = []

    async def fake_call(api_key, model, messages, temperature, max_tokens, json_mode, base_url=None,
                        stop=None, reasoning=None):
        recorded.append(reasoning)
        return LLMResponse("ok", finish_reason="stop")

    monkeypatch.setattr(llm_router, "_call_openai_compatible", fake_call)
    asyncio.run(_client().complete([{"role": "user", "content": "x"}], tier="agent"))
    assert recorded == [None]


def test_a_model_that_refuses_none_gets_low_and_keeps_it(monkeypatch):
    recorded = []

    async def fake_call(api_key, model, messages, temperature, max_tokens, json_mode, base_url=None,
                        stop=None, reasoning=None):
        recorded.append(reasoning)
        if reasoning == {"effort": "none"}:
            raise ProviderError(400, "Reasoning is mandatory for this endpoint and cannot be disabled.")
        return LLMResponse("ok", finish_reason="stop")

    monkeypatch.setattr(llm_router, "_call_openai_compatible", fake_call)
    monkeypatch.setattr(llm_router, "_effort_none_rejected", set())
    client = _client()
    first = asyncio.run(client.complete([{"role": "user", "content": "x"}], tier="heavy", reasoning_effort="none"))
    second = asyncio.run(client.complete([{"role": "user", "content": "x"}], tier="heavy", reasoning_effort="none"))
    assert recorded == [{"effort": "none"}, {"effort": "low"}, {"effort": "low"}]
    assert first.reasoning_mode == second.reasoning_mode == "effort=low"


def test_openai_gets_no_reasoning_parameter(monkeypatch):
    recorded = []

    async def fake_call(api_key, model, messages, temperature, max_tokens, json_mode, base_url=None,
                        stop=None, reasoning=None):
        recorded.append(reasoning)
        return LLMResponse("ok", finish_reason="stop")

    monkeypatch.setattr(llm_router, "_call_openai_compatible", fake_call)
    result = asyncio.run(_client("openai").complete([{"role": "user", "content": "x"}], tier="heavy",
                                                    reasoning_effort="low"))
    assert recorded == [None]
    assert result.reasoning_mode == "provider_default"


def test_native_anthropic_reads_the_text_blocks_only(monkeypatch):
    import anthropic

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="thinking", thinking=""),
                         SimpleNamespace(type="text", text="Part one. "),
                         SimpleNamespace(type="text", text="Part two.")],
                stop_reason="max_tokens", usage=SimpleNamespace(input_tokens=10, output_tokens=20))

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

        async def close(self):
            pass

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    result = asyncio.run(llm_router._call_anthropic("test-key", "claude-test", [{"role": "user", "content": "x"}],
                                                    0.2, 100))
    assert str(result) == "Part one. Part two."
    assert result.finish_reason == "length"


class RecordingLLM:
    def __init__(self):
        self.kwargs = []

    async def complete(self, messages, **kwargs):
        self.kwargs.append(kwargs)
        return LLMResponse("done", finish_reason="stop")


def test_report_calls_use_the_report_budget_and_effort(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_MAX_TOKENS", 24000)
    monkeypatch.setattr(Config, "REPORT_REASONING_EFFORT", "minimal")
    llm = RecordingLLM()
    agent = ReportAgent(llm=llm)
    asyncio.run(agent._complete([{"role": "user", "content": "x"}], stop=["OBSERVATION:"]))
    assert llm.kwargs == [{"tier": "heavy", "temperature": agent.temperature, "max_tokens": 24000,
                           "stop": ["OBSERVATION:"], "reasoning_effort": "minimal"}]


def test_heavy_call_sites_read_their_budget_from_the_config():
    import inspect

    from app.core import graph_builder
    from app.population import demographer, persona_generator

    assert "max_tokens=Config.GRAPH_MAX_TOKENS" in inspect.getsource(graph_builder)
    assert "max_tokens=Config.DEMOGRAPHER_MAX_TOKENS" in inspect.getsource(demographer)
    assert "max_tokens=Config.PERSONA_MAX_TOKENS" in inspect.getsource(persona_generator)
