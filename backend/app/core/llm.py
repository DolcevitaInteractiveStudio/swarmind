"""
SwarMind LLM Client — Groq-first with OpenAI-compatible fallback.

Three tiers:
  heavy  → llama-3.3-70b-versatile   (graph extraction, report)
  agent  → mixtral-8x7b-32768        (persona gen, key agents)
  fast   → llama-3.1-8b-instant      (mass simulation turns)
"""
from __future__ import annotations
from typing import Any

import asyncio
import time

import structlog
from groq import AsyncGroq, RateLimitError, APIStatusError

from ..config import Config
from .llm_response import from_chat_completion, llm_log_fields
from .llm_retry import llm_retry

log = structlog.get_logger()


class LLMClient:
    """Async LLM client with Groq primary + fallback support."""

    def __init__(self, config: Config | None = None):
        cfg = config or Config()
        self._api_key = cfg.GROQ_API_KEY
        self._models = {
            "heavy": cfg.GROQ_MODEL_HEAVY,
            "agent": cfg.GROQ_MODEL_AGENT,
            "fast": cfg.GROQ_MODEL_FAST,
        }
        # Rate-limit accounting per model
        self._call_counts: dict[str, int] = {}

    # ── Public interface ──────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[dict],
        tier: str = "agent",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
        stop: list[str] | None = None,
    ) -> str:
        """Call Groq with auto-retry on recoverable errors."""
        model = self._models.get(tier, self._models["agent"])
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if stop:
            kwargs["stop"] = stop

        return await self._call_with_retry(**kwargs)

    async def batch_complete(
        self,
        prompts: list[list[dict]],
        tier: str = "fast",
        temperature: float = 0.8,
        max_tokens: int = 512,
        concurrency: int = 20,
    ) -> list[str]:
        """Run many completions concurrently, respecting a semaphore."""
        sem = asyncio.Semaphore(concurrency)

        async def _one(msgs: list[dict]) -> str:
            async with sem:
                return await self.complete(
                    msgs, tier=tier, temperature=temperature, max_tokens=max_tokens
                )

        return await asyncio.gather(*[_one(p) for p in prompts])

    # ── Internal ──────────────────────────────────────────────────────────

    @llm_retry
    async def _call_with_retry(self, **kwargs) -> str:
        model = kwargs.get("model", "unknown")
        t0 = time.monotonic()
        try:
            from groq import AsyncGroq as _AsyncGroq
            _client = _AsyncGroq(api_key=self._api_key)
            try:
                resp = await _client.chat.completions.create(**kwargs)
            finally:
                await _client.close()
            elapsed = time.monotonic() - t0
            self._call_counts[model] = self._call_counts.get(model, 0) + 1
            result = from_chat_completion(resp)
            log.debug(
                "groq_call_ok",
                model=model,
                elapsed_ms=round(elapsed * 1000),
                tokens=resp.usage.total_tokens if resp.usage else "?",
                **llm_log_fields(result),
            )
            return result
        except RateLimitError:
            log.warning("groq_rate_limit", model=model)
            raise
        except APIStatusError as e:
            log.error("groq_api_error", model=model, status=e.status_code, msg=str(e))
            raise


# Module-level singleton (lazy-loaded)
_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def _build_llm_from_credential(provider, credential_id, model_heavy=None, model_agent=None, model_fast=None):
    """
    Costruisce un MultiProviderLLM dato un provider + credential_id.
    Ritorna None se qualcosa manca (cosi' chi chiama puo' fare fallback).
    """
    import os
    import psycopg2
    from app.core.llm_router import MultiProviderLLM, LLMConfig
    from app.models.llm_credential import SUPPORTED_PROVIDERS

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or not credential_id:
        return None

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT encrypted_api_key, model_heavy, model_agent, model_fast FROM llm_credentials WHERE id=%s AND is_active=true",
            (str(credential_id),)
        )
        cred_row = cur.fetchone()
        cur.close(); conn.close()

        if not cred_row:
            return None

        encrypted_key, cred_heavy, cred_agent, cred_fast = cred_row
        encryption_key = os.environ.get("ENCRYPTION_KEY", "")
        if not encryption_key:
            return None
        from cryptography.fernet import Fernet
        api_key = Fernet(encryption_key.encode()).decrypt(encrypted_key.encode()).decode()

        meta = SUPPORTED_PROVIDERS.get(provider, {})
        models = meta.get("models", [])

        # Precedenza: override passato > modello nella credenziale > primo della lista
        llm_config = LLMConfig(
            provider=provider,
            api_key=api_key,
            model_heavy=model_heavy or cred_heavy or (models[0] if models else ""),
            model_agent=model_agent or cred_agent or (models[0] if models else ""),
            model_fast=model_fast or cred_fast or (models[-1] if models else ""),
            base_url=meta.get("base_url") if provider == "openrouter" else None,
        )
        return MultiProviderLLM(llm_config)
    except Exception as e:
        log.warning("build_llm_from_credential_failed", error=str(e))
        return None


def get_llm_for_project(project_id: str | None = None) -> Any:
    """
    Restituisce il client LLM configurato per il progetto.
    Fallback: client Groq di sistema.
    """
    if not project_id:
        return get_llm()

    try:
        import os
        import psycopg2

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return get_llm()

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT llm_provider, llm_credential_id, model_heavy, model_agent, model_fast FROM projects WHERE id=%s",
            (project_id,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()

        if not row:
            return get_llm()

        provider, credential_id, m_heavy, m_agent, m_fast = row

        # Se il progetto non ha nulla configurato, usa sistema
        if not provider or not credential_id:
            return get_llm()

        client = _build_llm_from_credential(provider, credential_id, m_heavy, m_agent, m_fast)
        if client is None:
            log.warning("llm_for_project_fallback", project_id=project_id, reason="build_failed")
            return get_llm()

        log.info("llm_for_project", project_id=project_id, provider=provider,
                 model_heavy=m_heavy, model_fast=m_fast)
        return client

    except Exception as e:
        log.warning("get_llm_for_project_fallback", project_id=project_id, error=str(e))
        return get_llm()


def get_llm_for_simulation(simulation_id: str | None = None) -> Any:
    """
    Restituisce il client LLM per la simulazione.
    Cascata: sim.llm_* -> project.llm_* -> Groq di sistema.
    """
    if not simulation_id:
        return get_llm()

    try:
        import os
        import psycopg2

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return get_llm()

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Leggi sim + project_id
        cur.execute(
            "SELECT llm_provider, llm_credential_id, model_heavy, model_agent, model_fast, project_id FROM simulations WHERE id=%s",
            (simulation_id,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()

        if not row:
            return get_llm()

        sim_provider, sim_cred_id, sim_heavy, sim_agent, sim_fast, project_id = row

        # 1. Tenta LLM specifico della simulazione
        if sim_provider and sim_cred_id and sim_provider != "groq":
            client = _build_llm_from_credential(sim_provider, sim_cred_id, sim_heavy, sim_agent, sim_fast)
            if client:
                log.info("llm_for_simulation", sim_id=simulation_id, source="sim", provider=sim_provider)
                return client

        # 2. Fallback a LLM del progetto
        if project_id:
            project_client = get_llm_for_project(project_id)
            # Se get_llm_for_project ha tornato non-default, usalo
            # (e' un MultiProviderLLM se configurato, LLMClient Groq altrimenti)
            return project_client

        # 3. Fallback ultimo al Groq di sistema
        return get_llm()

    except Exception as e:
        log.warning("get_llm_for_simulation_fallback", sim_id=simulation_id, error=str(e))
        return get_llm()
