"""
SwarMind Multi-Provider LLM Router

Supporta 4 provider con routing automatico per tier (heavy/agent/fast):
  - Groq          → SDK nativo groq (più veloce per Llama/Mixtral)
  - Anthropic      → SDK anthropic nativo (Messages API)
  - OpenAI         → SDK openai
  - OpenRouter     → openai-compatible (base_url override)

Il router:
  1. Riceve le credenziali dell'utente (decifrate dal DB)
  2. Istanzia il client corretto
  3. Gestisce retry sugli errori recuperabili con backoff esponenziale (llm_retry)
  4. Traccia l'utilizzo per quota/billing
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

import structlog

from .llm_response import LLMResponse, from_chat_completion, llm_log_fields
from .llm_retry import llm_retry

log = structlog.get_logger()


@dataclass
class LLMConfig:
    """Configurazione completa per una chiamata LLM."""
    provider: str        # groq | anthropic | openai | openrouter
    api_key: str
    model_heavy: str
    model_agent: str
    model_fast: str
    base_url: str | None = None  # override per openrouter


# ── Fallback di sistema (usa GROQ_API_KEY dall'env) ───────────────────────────
def _system_config() -> LLMConfig:
    from flask import current_app
    cfg = current_app.config
    return LLMConfig(
        provider="groq",
        api_key=cfg["GROQ_API_KEY"],
        model_heavy=cfg["GROQ_MODEL_HEAVY"],
        model_agent=cfg["GROQ_MODEL_AGENT"],
        model_fast=cfg["GROQ_MODEL_FAST"],
    )


def system_key_configured() -> bool:
    """True when GROQ_API_KEY is set: users without a credential of their own can use it."""
    from flask import current_app
    return bool((current_app.config.get("GROQ_API_KEY") or "").strip())


def user_has_llm_access(user_id: str) -> bool:
    """A usable LLM path exists for the user: the system key, or an active credential of theirs.

    Without either, every LLM call would fail with HTTP 401 (empty key): project upload and
    simulation create refuse up front with no_llm_provider and the UI points to AI connections.
    """
    if system_key_configured():
        return True
    from app.models import LLMCredential
    return LLMCredential.query.filter_by(user_id=user_id, is_active=True).first() is not None


def config_for_user(user_id: str | None, provider: str | None = None,
                    credential_id: str | None = None) -> LLMConfig:
    """
    Carica la configurazione LLM per un utente specifico.
    Se non ha credenziali proprie, usa il fallback di sistema.
    """
    if not user_id:
        return _system_config()

    try:
        from app.models import LLMCredential
        q = LLMCredential.query.filter_by(user_id=user_id, is_active=True)
        if credential_id:
            q = q.filter_by(id=credential_id)
        elif provider:
            q = q.filter_by(provider=provider)
        cred = q.first()
        if not cred:
            return _system_config()

        from app.models.llm_credential import SUPPORTED_PROVIDERS
        meta = SUPPORTED_PROVIDERS.get(cred.provider, {})
        models = meta.get("models", [])

        return LLMConfig(
            provider=cred.provider,
            api_key=cred.get_api_key(),
            model_heavy=cred.model_heavy or models[0] if models else "",
            model_agent=cred.model_agent or models[0] if models else "",
            model_fast=cred.model_fast or models[-1] if models else "",
            base_url=meta.get("base_url") if cred.provider == "openrouter" else None,
        )
    except Exception as e:
        log.warning("config_for_user_error", user_id=user_id, error=str(e))
        return _system_config()


# ── Chiamate per provider ─────────────────────────────────────────────────────
# Ogni chiamata crea il proprio client e lo chiude prima di ritornare, nell'event loop che lo
# usa. Un client lasciato aperto viene chiuso dal garbage collector quando capita, spesso durante
# il loop del task successivo (run_async ne crea uno per task): le sue connessioni appartengono al
# loop gia' chiuso e httpx registra "Task exception was never retrieved ... Event loop is closed".


async def _closing(client, call):
    """Esegue call() (con i suoi retry) e chiude il client in ogni caso."""
    try:
        return await call()
    finally:
        await client.close()


async def _call_groq(api_key: str, model: str, messages: list[dict],
                     temperature: float, max_tokens: int,
                     json_mode: bool, stop: list[str] | None = None) -> str:
    from groq import AsyncGroq
    client = AsyncGroq(api_key=api_key)
    kwargs: dict[str, Any] = dict(model=model, messages=messages,
                                   temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if stop:
        kwargs["stop"] = stop

    @llm_retry
    async def _do():
        r = await client.chat.completions.create(**kwargs)
        return from_chat_completion(r)
    return await _closing(client, _do)


async def _call_anthropic(api_key: str, model: str, messages: list[dict],
                           temperature: float, max_tokens: int,
                           stop: list[str] | None = None, **_) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Separa system prompt dai messaggi utente/assistant
    system_prompt = ""
    chat_messages = []
    for m in messages:
        if m["role"] == "system":
            system_prompt = m["content"]
        else:
            chat_messages.append(m)

    @llm_retry
    async def _do():
        create_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or anthropic.NOT_GIVEN,
            messages=chat_messages,
        )
        if stop:
            create_kwargs["stop_sequences"] = stop
        r = await client.messages.create(**create_kwargs)
        return LLMResponse(
            r.content[0].text if r.content else "",
            # Normalizza sul valore OpenAI: chi legge finish_reason non distingue i provider
            finish_reason="length" if r.stop_reason == "max_tokens" else r.stop_reason,
            prompt_tokens=r.usage.input_tokens,
            completion_tokens=r.usage.output_tokens,
        )
    return await _closing(client, _do)


async def _call_openai_compatible(api_key: str, model: str, messages: list[dict],
                                   temperature: float, max_tokens: int,
                                   json_mode: bool, base_url: str | None = None,
                                   stop: list[str] | None = None,
                                   reasoning: dict | None = None) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    kwargs: dict[str, Any] = dict(model=model, messages=messages,
                                   temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if stop:
        kwargs["stop"] = stop
    if reasoning:
        kwargs["extra_body"] = {"reasoning": reasoning}

    @llm_retry
    async def _do():
        r = await client.chat.completions.create(**kwargs)
        return from_chat_completion(r)
    return await _closing(client, _do)


# ── Reasoning sul tier fast (OpenRouter) ──────────────────────────────────────
# Sui modelli con reasoning attivo di default, il reasoning consuma il budget
# max_tokens dei turni di simulazione e lascia risposte vuote: qui viene spento.
# I modelli con reasoning obbligatorio rifiutano "none": il primo 400 li sposta su
# "low" con un budget piu' alto. Il metadato `mandatory` del listing OpenRouter non
# e' disponibile a runtime, e il testo esatto dell'errore non e' documentato.

REASONING_MODE_NONE = "none"
REASONING_MODE_LOW_FALLBACK = "low_fallback"
_REASONING_EFFORT = {REASONING_MODE_NONE: "none", REASONING_MODE_LOW_FALLBACK: "low"}
_LOW_FALLBACK_MIN_MAX_TOKENS = 2048

# Per modello e a livello di modulo: ogni agente ha il proprio MultiProviderLLM.
# Dura quanto il processo worker, quindi anche oltre la singola simulazione.
_reasoning_modes: dict[str, str] = {}
_reasoning_locks: WeakKeyDictionary = WeakKeyDictionary()


def _reasoning_lock(model: str) -> asyncio.Lock:
    """Lock per modello e per event loop: ogni task Celery esegue su un proprio loop."""
    locks = _reasoning_locks.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(model, asyncio.Lock())


def _rejects_reasoning_none(error: Exception) -> bool:
    # str(error) include il body completo, anche i messaggi del provider a monte
    return getattr(error, "status_code", None) == 400 and "reasoning" in str(error).lower()


# ── Temperatura per i modelli Anthropic ───────────────────────────────────────
# Anthropic accetta temperature fino a 1.0, ma i turni di simulazione inviano valori
# piu' alti (decide_action fino a 1.1, evento di diversita' 1.2). I modelli "~anthropic/"
# sono alias OpenRouter dei modelli Anthropic.

_ANTHROPIC_MAX_TEMPERATURE = 1.0
_temperature_clamped_models: set[str] = set()


def _clamp_temperature(provider: str, model: str, temperature: float) -> float:
    is_anthropic = provider == "anthropic" or (
        provider == "openrouter" and (model or "").removeprefix("~").startswith("anthropic/")
    )
    if not is_anthropic or temperature <= _ANTHROPIC_MAX_TEMPERATURE:
        return temperature
    if model not in _temperature_clamped_models:
        _temperature_clamped_models.add(model)
        log.info("temperature_clamped", provider=provider, model=model,
                 requested=temperature, sent=_ANTHROPIC_MAX_TEMPERATURE)
    return _ANTHROPIC_MAX_TEMPERATURE


# ── Router principale ─────────────────────────────────────────────────────────

class MultiProviderLLM:
    """
    Client LLM unificato che instrada verso il provider corretto.
    Instanzia uno per simulazione, passando la LLMConfig dell'utente.
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def _model_for_tier(self, tier: str) -> str:
        return {
            "heavy": self.config.model_heavy,
            "agent": self.config.model_agent,
            "fast": self.config.model_fast,
        }.get(tier, self.config.model_agent)

    async def complete(self, messages: list[dict], tier: str = "agent",
                       temperature: float = 0.7, max_tokens: int = 1024,
                       json_mode: bool = False,
                       stop: list[str] | None = None) -> str:
        model = self._model_for_tier(tier)
        t0 = time.monotonic()
        provider = self.config.provider
        temperature = _clamp_temperature(provider, model, temperature)

        try:
            if provider == "groq":
                result = await _call_groq(
                    self.config.api_key, model, messages,
                    temperature, max_tokens, json_mode, stop=stop)

            elif provider == "anthropic":
                result = await _call_anthropic(
                    self.config.api_key, model, messages,
                    temperature, max_tokens, stop=stop)

            elif provider == "openrouter" and tier == "fast":
                result = await self._complete_openrouter_fast(
                    model, messages, temperature, max_tokens, json_mode, stop)

            elif provider in ("openai", "openrouter"):
                result = await _call_openai_compatible(
                    self.config.api_key, model, messages,
                    temperature, max_tokens, json_mode,
                    base_url=self.config.base_url, stop=stop)
            else:
                raise ValueError(f"Unknown provider: {provider}")

            elapsed = round((time.monotonic() - t0) * 1000)
            log.debug("llm_call_ok", provider=provider, model=model,
                      tier=tier, elapsed_ms=elapsed, **llm_log_fields(result))
            return result

        except Exception as e:
            log.error("llm_call_error", provider=provider, model=model,
                      status=getattr(e, "status_code", None), error=str(e))
            raise

    async def _complete_openrouter_fast(self, model: str, *call_args) -> str:
        # Modello mai visto: una sola chiamata decide, quelle concorrenti ne attendono
        # l'esito invece di ricevere tutte lo stesso 400
        if model not in _reasoning_modes:
            async with _reasoning_lock(model):
                if model not in _reasoning_modes:
                    return await self._call_with_reasoning_decision(model, *call_args)
        return await self._call_with_reasoning_decision(model, *call_args)

    async def _call_with_reasoning_decision(self, model: str, *call_args) -> str:
        mode = _reasoning_modes.get(model, REASONING_MODE_NONE)
        try:
            result = await self._call_with_reasoning_mode(mode, model, *call_args)
        except Exception as e:
            if mode != REASONING_MODE_NONE or not _rejects_reasoning_none(e):
                raise
            _reasoning_modes[model] = REASONING_MODE_LOW_FALLBACK
            log.warning("reasoning_mode_selected", provider=self.config.provider, model=model,
                        reasoning_mode=REASONING_MODE_LOW_FALLBACK, error=str(e)[:300])
            return await self._call_with_reasoning_mode(REASONING_MODE_LOW_FALLBACK, model, *call_args)
        if model not in _reasoning_modes:
            _reasoning_modes[model] = REASONING_MODE_NONE
            log.info("reasoning_mode_selected", provider=self.config.provider, model=model,
                     reasoning_mode=REASONING_MODE_NONE)
        return result

    async def _call_with_reasoning_mode(self, mode: str, model: str, messages: list[dict],
                                        temperature: float, max_tokens: int, json_mode: bool,
                                        stop: list[str] | None) -> str:
        if mode == REASONING_MODE_LOW_FALLBACK:
            max_tokens = max(max_tokens, _LOW_FALLBACK_MIN_MAX_TOKENS)
        result = await _call_openai_compatible(
            self.config.api_key, model, messages,
            temperature, max_tokens, json_mode,
            base_url=self.config.base_url, stop=stop,
            reasoning={"effort": _REASONING_EFFORT[mode]})
        result.reasoning_mode = mode
        return result

    async def batch_complete(self, prompts: list[list[dict]], tier: str = "fast",
                              temperature: float = 0.8, max_tokens: int = 512,
                              concurrency: int = 20) -> list[str]:
        sem = asyncio.Semaphore(concurrency)

        async def _one(msgs):
            async with sem:
                return await self.complete(msgs, tier=tier,
                                           temperature=temperature, max_tokens=max_tokens)

        return await asyncio.gather(*[_one(p) for p in prompts], return_exceptions=False)


# ── Verifica credenziale (ping test) ─────────────────────────────────────────

async def verify_credential(provider: str, api_key: str,
                              model: str | None = None, lang: str = "en") -> tuple[bool, str]:
    """
    Invia un messaggio minimo per verificare che la chiave funzioni.
    Restituisce (ok: bool, message: str); i messaggi fissi nella lingua lang (catalogo).
    """
    from app.core.i18n import t
    from app.models.llm_credential import SUPPORTED_PROVIDERS
    meta = SUPPORTED_PROVIDERS.get(provider, {})
    test_model = model or (meta.get("models") or ["gpt-4o-mini"])[0]
    test_messages = [{"role": "user", "content": "Reply with the single word: OK"}]

    try:
        if provider == "groq":
            result = await _call_groq(api_key, test_model, test_messages,
                                       0.0, 10, False)
        elif provider == "anthropic":
            result = await _call_anthropic(api_key, test_model, test_messages,
                                            0.0, 10)
        elif provider in ("openai", "openrouter"):
            base_url = meta.get("base_url") if provider == "openrouter" else None
            result = await _call_openai_compatible(api_key, test_model, test_messages,
                                                    0.0, 10, False, base_url)
        else:
            return False, t(lang, "credentials.unknown_provider", provider=provider)

        if result:
            return True, t(lang, "credentials.verified")
        return False, t(lang, "credentials.empty_reply")

    except Exception as e:
        return False, str(e)
