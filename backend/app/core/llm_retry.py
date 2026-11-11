"""Politica di retry unica per le chiamate LLM di tutti i provider."""
from __future__ import annotations

import anthropic
import groq
import httpx
import openai
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = structlog.get_logger()

RETRYABLE_STATUS = {408, 409, 429}
_NETWORK_ERRORS = (
    groq.APIConnectionError,
    openai.APIConnectionError,
    anthropic.APIConnectionError,
    httpx.TransportError,
)


def is_retryable_llm_error(error: BaseException) -> bool:
    """Gli altri 4xx (modello inesistente, chiave errata, richiesta invalida) fallirebbero di nuovo."""
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS or status >= 500
    return isinstance(error, _NETWORK_ERRORS)


def _log_retry(retry_state) -> None:
    error = retry_state.outcome.exception()
    log.warning(
        "llm_retry",
        status=getattr(error, "status_code", None),
        error_type=type(error).__name__,
        attempt=retry_state.attempt_number,
        wait_s=round(retry_state.next_action.sleep, 1),
    )


# reraise: chi chiama riceve l'errore del provider, non un RetryError che lo nasconde
llm_retry = retry(
    retry=retry_if_exception(is_retryable_llm_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(6),
    before_sleep=_log_retry,
    reraise=True,
)
