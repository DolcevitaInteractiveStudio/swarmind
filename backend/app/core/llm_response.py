"""
Risposta LLM con metadati.

LLMResponse e' una str: i chiamanti esistenti restano invariati, chi serve
osservabilita' legge finish_reason e token usage dagli attributi. I metadati
viaggiano con la risposta, quindi restano corretti anche con chiamate
concorrenti (asyncio.gather).
"""
from __future__ import annotations

from typing import Any


class LLMResponse(str):
    def __new__(
        cls,
        text: str | None = "",
        finish_reason: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ):
        obj = super().__new__(cls, text or "")
        obj.finish_reason = finish_reason
        obj.prompt_tokens = prompt_tokens
        obj.completion_tokens = completion_tokens
        obj.reasoning_tokens = reasoning_tokens
        obj.reasoning_mode = reasoning_mode
        return obj


def from_chat_completion(r: Any) -> LLMResponse:
    """Costruisce una LLMResponse da una risposta OpenAI-compatible (OpenAI, OpenRouter, Groq)."""
    choice = r.choices[0]
    usage = r.usage
    details = getattr(usage, "completion_tokens_details", None)
    # Gli SDK piu' vecchi espongono i campi extra del provider come dict, non come oggetto
    if isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")
    else:
        reasoning_tokens = getattr(details, "reasoning_tokens", None)
    return LLMResponse(
        choice.message.content,
        finish_reason=choice.finish_reason,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        reasoning_tokens=reasoning_tokens,
    )


def llm_log_fields(response: Any) -> dict:
    """Campi di log di una risposta. Tutti None se il client ha ritornato una str semplice."""
    return {
        "finish_reason": getattr(response, "finish_reason", None),
        "prompt_tokens": getattr(response, "prompt_tokens", None),
        "completion_tokens": getattr(response, "completion_tokens", None),
        "reasoning_tokens": getattr(response, "reasoning_tokens", None),
        "reasoning_mode": getattr(response, "reasoning_mode", None),
    }
