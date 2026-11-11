"""
Client Chroma del processo, con timeout, e chiamate dal loop asyncio fuori dal loop.

Il client HTTP di chromadb 1.0.21 apre la sessione httpx con timeout=None e non ha un'impostazione
per cambiarlo (HttpClient fissa chroma_api_impl, Settings non ha timeout lato client): un server che
accetta la connessione e non risponde blocca la chiamata per sempre. Il 2026-11-08 una simulazione e'
rimasta ferma cosi' su get_user_identity, nel costruttore del client, dentro il loop asyncio.

  - _install_http_timeout mette il timeout sulla sessione appena creata, prima della prima richiesta;
    vale per ogni client HTTP del processo (memoria degli agenti, KB, pulizia).
  - get_chroma: un client per processo e configurazione; dopo un fork (prefork di Celery) se ne crea
    uno nuovo, cosi' le connessioni del padre non si condividono.
  - run_chroma esegue una chiamata sincrona in un pool di thread dedicato, con un tetto di tempo
    complessivo: una chiamata bloccata non ferma il loop.
  - Dopo un timeout o un errore di rete Chroma si considera giu' per CHROMA_COOLDOWN_SECONDS:
    run_chroma fallisce subito (ChromaSkipped) invece di aspettare ogni volta il suo timeout.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import chromadb
import httpx
import structlog
from chromadb.config import Settings

from ..config import Config

log = structlog.get_logger()

# Thread per le chiamate a Chroma dal loop, per processo. Chroma 1.0.21 su un nodo scrive su SQLite,
# un writer alla volta: oltre poche richieste concorrenti si fa solo coda sul server, con socket e
# file aperti in piu' (ulimit -n 1024 nell'incidente). 8 bastano ai ~20 agenti di un round (una
# lettura e una scrittura di memoria a testa, pochi ms l'una) e con Chroma bloccato restano occupati
# al massimo 8 thread, ciascuno per non piu' del timeout HTTP.
CHROMA_MAX_THREADS = 8

HTTP_TIMEOUT = httpx.Timeout(Config.CHROMA_READ_TIMEOUT, connect=Config.CHROMA_CONNECT_TIMEOUT)

# Messaggi di chromadb e del server che indicano Chroma non raggiungibile o non sano
_OUTAGE_MARKERS = ("Could not connect to a Chroma server", "Database error")


class ChromaUnavailable(RuntimeError):
    """Chroma non ha risposto entro il tempo previsto."""


class ChromaSkipped(ChromaUnavailable):
    """Chiamata non fatta: Chroma e' in pausa dopo un errore recente."""


def _install_http_timeout() -> None:
    """Mette HTTP_TIMEOUT sulla sessione httpx di ogni client HTTP di chromadb, prima della prima richiesta.

    Si installa alla creazione del primo client (idempotente), non all'import del modulo.
    """
    from chromadb.api.fastapi import FastAPI

    if getattr(FastAPI.__init__, "_swarmind_timeout", False):
        return
    original = FastAPI.__init__

    @functools.wraps(original)
    def __init__(self, system):
        original(self, system)
        self._session.timeout = HTTP_TIMEOUT

    __init__._swarmind_timeout = True
    FastAPI.__init__ = __init__


def chroma_settings() -> tuple[str, int, str]:
    """Host, porta e token: dal config Flask se c'e' un app context, altrimenti dall'ambiente."""
    try:
        from flask import current_app
        cfg = current_app.config
        return (
            cfg.get("CHROMA_HOST", os.environ.get("CHROMA_HOST", "localhost")),
            int(cfg.get("CHROMA_PORT", os.environ.get("CHROMA_PORT", 8000))),
            cfg.get("CHROMA_TOKEN", os.environ.get("CHROMA_TOKEN", "")),
        )
    except RuntimeError:
        return (
            os.environ.get("CHROMA_HOST", "localhost"),
            int(os.environ.get("CHROMA_PORT", 8000)),
            os.environ.get("CHROMA_TOKEN", ""),
        )


# Due lock: la creazione del client fa richieste HTTP, il pool si prende dal thread del loop
_lock = threading.Lock()
_executor_lock = threading.Lock()
_clients: dict[tuple[str, int, str], object] = {}
_clients_pid: int | None = None
_executor: ThreadPoolExecutor | None = None
_executor_pid: int | None = None
# time.monotonic() fino a cui le chiamate dal loop saltano Chroma
_down_until = 0.0


def _new_client(host: str, port: int, token: str):
    _install_http_timeout()
    auth_settings = {}
    if token:
        auth_settings = {
            "chroma_client_auth_provider": "chromadb.auth.token_authn.TokenAuthClientProvider",
            "chroma_client_auth_credentials": token,
        }
    return chromadb.HttpClient(
        host=host,
        port=port,
        tenant="default_tenant",
        database="default_database",
        settings=Settings(**auth_settings) if auth_settings else Settings(),
    )


def get_chroma(host: str | None = None, port: int | None = None, token: str | None = None):
    """Il client Chroma di questo processo, creato al primo uso. Senza argomenti usa chroma_settings().

    La creazione fa gia' richieste HTTP (identita' e tenant): dal loop asyncio va chiamata con run_chroma.
    """
    global _clients_pid
    if host is None or port is None or token is None:
        default_host, default_port, default_token = chroma_settings()
        host = default_host if host is None else host
        port = default_port if port is None else port
        token = default_token if token is None else token
    key = (str(host), int(port), token or "")
    with _lock:
        if _clients_pid != os.getpid():
            # Processo figlio: niente connessioni ereditate dal padre
            _clients.clear()
            _clients_pid = os.getpid()
        client = _clients.get(key)
        if client is None:
            client = _new_client(*key)
            _clients[key] = client
        return client


def _get_executor() -> ThreadPoolExecutor:
    global _executor, _executor_pid
    with _executor_lock:
        if _executor is None or _executor_pid != os.getpid():
            _executor = ThreadPoolExecutor(max_workers=CHROMA_MAX_THREADS, thread_name_prefix="chroma")
            _executor_pid = os.getpid()
        return _executor


def is_outage(exc: BaseException) -> bool:
    """True se l'errore dice che Chroma non risponde o non e' sano (non un errore della singola richiesta)."""
    if isinstance(exc, (ChromaUnavailable, httpx.TransportError, asyncio.TimeoutError)):
        return True
    # chromadb.errors.InternalError (5xx del server), per nome: chi classifica un errore non deve
    # poterne sollevare un altro
    if any(cls.__name__ == "InternalError" and cls.__module__.startswith("chromadb")
           for cls in type(exc).__mro__):
        return True
    text = str(exc)
    return any(marker in text for marker in _OUTAGE_MARKERS)


def chroma_available() -> bool:
    return time.monotonic() >= _down_until


def _mark_down(op: str, exc: BaseException) -> None:
    global _down_until
    was_up = chroma_available()
    _down_until = time.monotonic() + Config.CHROMA_COOLDOWN_SECONDS
    if was_up:
        log.warning("chroma_unavailable", op=op, error=error_text(exc),
                    cooldown_s=Config.CHROMA_COOLDOWN_SECONDS)


def _mark_up(op: str) -> None:
    global _down_until
    if _down_until:
        _down_until = 0.0
        log.info("chroma_available_again", op=op)


def error_text(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:300]


async def run_chroma(op: str, fn, *args, timeout: float, **kwargs):
    """Esegue fn(*args, **kwargs), una chiamata sincrona a Chroma, in un thread entro timeout secondi.

    Solleva ChromaSkipped se Chroma e' in pausa, ChromaUnavailable allo scadere del tempo (il thread
    finisce da solo entro il timeout HTTP), altrimenti l'errore di fn.
    """
    if not chroma_available():
        raise ChromaSkipped("Chroma in pausa dopo un errore recente")
    loop = asyncio.get_running_loop()
    # Il contesto del chiamante, come asyncio.to_thread: dentro un app context Flask host e porta
    # vengono ancora dal config dell'app
    context = contextvars.copy_context()
    future = loop.run_in_executor(_get_executor(), functools.partial(context.run, fn, *args, **kwargs))
    try:
        result = await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        exc = ChromaUnavailable(f"nessuna risposta da Chroma entro {timeout:g}s")
        _mark_down(op, exc)
        raise exc from None
    except Exception as e:
        if is_outage(e):
            _mark_down(op, e)
        raise
    _mark_up(op)
    return result
