"""
Stato di simulazioni e grafo nel DB lungo la pipeline Celery.

psycopg2 diretto come nel resto dei task: il worker non ha un app context Flask.
Un DB irraggiungibile non deve far fallire una simulazione in corso: le scritture lo
registrano e proseguono, e le righe rimaste indietro le chiude reap_stale al riavvio.
"""
from __future__ import annotations

import base64
import json
import os
import re

import structlog

from app.core import i18n

log = structlog.get_logger()

PHASE_GRAPH = "graph"
PHASE_SPAWN = "spawn"
PHASE_ROUNDS = "rounds"
PHASE_REPORT = "report"

RUNNING_STATUSES = ("BUILDING_GRAPH", "SPAWNING_AGENTS", "RUNNING", "GENERATING_REPORT")

_NOT_CLOSED = "status NOT IN ('COMPLETED', 'FAILED', 'STOPPED')"

_MAX_MESSAGE_CHARS = 400

# Quota restituita: fallimenti prima del report. Il report fallito o lo stop dell'utente non la restituiscono
_REFUND_PHASES = (PHASE_GRAPH, PHASE_SPAWN, PHASE_ROUNDS)
_REFUND_STALE_STATUSES = ("BUILDING_GRAPH", "SPAWNING_AGENTS", "RUNNING")
# Chiave o modello dell'utente rifiutati dal provider: restituiti anche questi, ma al massimo
# CREDENTIAL_REFUNDS_PER_MONTH al mese per utente
_CREDENTIAL_STATUSES = (401, 403, 404)
CREDENTIAL_REFUNDS_PER_MONTH = 3
REFUND_REASON_CREDENTIAL = "credential_or_model"
REFUND_REASON_STALE = "stale"
REFUND_REASON_WORKER_RESTART = "worker_restart"

# I messaggi per l'utente si salvano come codice + parametri (error_detail, graph_error_detail) e si
# rendono alla lettura nella lingua della richiesta (locales/<lang>.yml, sezione lifecycle). La
# colonna di testo (error_message, graph_error) riceve la resa inglese: resta il segnale di stato
# usato nelle query e il testo per log e righe vecchie.
_PHASES = (PHASE_GRAPH, PHASE_SPAWN, PHASE_ROUNDS, PHASE_REPORT)
_LLM_STATUS_HINTS = frozenset((400, 401, 402, 403, 404, 408, 409, 422, 429))

_STALE_SIMULATION = {"key": "stale_simulation"}
_REDELIVERED = {"key": "redelivered"}
STOPPED_BY_USER_DETAIL = {"key": "stopped_by_user"}
_STALE_GRAPH = {"key": "stale_graph"}

# Task che cancella la collection di memoria Chroma di una simulazione chiusa (memory/memory_cleanup.py)
MEMORY_CLEANUP_TASK = "swarmind.delete_simulation_memory"

# Le risposte dei provider possono citare la chiave, e questo testo arriva nella UI
_SECRETS = (
    (re.compile(r"\b(?:sk|gsk|pk|rk|xai)[-_][A-Za-z0-9_*\-]{6,}"), "***"),
    (re.compile(r"(?i)bearer\s+\S+"), "Bearer ***"),
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://***@"),
)


def _redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def _provider_detail(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else ""


class LifecycleError(RuntimeError):
    """Errore dei task con un motivo per l'utente dal catalogo (lifecycle.reason.<key>).

    str() e' il testo inglese, per i log. Picklabile con chiave e parametri: Celery lo rispedisce
    al segnale task_failure senza ridurlo alla classe base.
    """

    def __init__(self, key: str, params: dict | None = None):
        self.key = key
        self.params = dict(params or {})
        super().__init__(i18n.t(i18n.DEFAULT_LANGUAGE, f"lifecycle.reason.{key}", **self.params))

    def __reduce__(self):
        return (self.__class__, (self.key, self.params))


def message_text(detail: dict, lang: str = i18n.DEFAULT_LANGUAGE) -> str:
    """Un messaggio codificato reso in lang, alla lunghezza massima della UI."""
    return i18n.render_coded(lang, detail, "lifecycle")[:_MAX_MESSAGE_CHARS]


def _stored(detail: dict) -> tuple[str, str]:
    """(testo inglese per la colonna di testo, JSON per la colonna strutturata)."""
    return message_text(detail), json.dumps(detail, ensure_ascii=False)


STOPPED_BY_USER_MESSAGE = message_text(STOPPED_BY_USER_DETAIL)


def _failure_reason(exc: BaseException) -> dict:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in _LLM_STATUS_HINTS:
            hint = f"llm_hint.{status}"
        else:
            hint = "llm_hint.server_error" if status >= 500 else "llm_hint.rejected"
        params = {"hint": {"key": hint}, "status": status}
        # Testo del provider: non si traduce
        detail = _redact(_provider_detail(exc))[:_MAX_MESSAGE_CHARS]
        if detail:
            params["detail"] = detail
        return {"key": "llm_error_detail" if detail else "llm_error", "params": params}
    if type(exc).__name__ == "WorkerLostError":
        return {"key": "reason.worker_lost"}
    if isinstance(exc, LifecycleError):
        return {"key": f"reason.{exc.key}", "params": exc.params}
    # Eccezione senza codice: il suo testo, cosi' com'e'
    return {"text": _redact(str(exc) or type(exc).__name__)[:_MAX_MESSAGE_CHARS]}


def failure_detail(phase: str, exc: BaseException) -> dict:
    """Messaggio breve per l'utente, come codice. L'eccezione completa resta nei log del worker."""
    key = f"phase_failed.{phase}" if phase in _PHASES else "phase_failed.other"
    return {"key": key, "params": {"reason": _failure_reason(exc)}}


def failure_message(phase: str, exc: BaseException) -> str:
    """failure_detail reso in inglese."""
    return message_text(failure_detail(phase, exc))


def _execute(sql: str, params: tuple) -> int | None:
    """Esegue una UPDATE e ritorna le righe toccate. None se non si puo' sapere."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount
        finally:
            conn.close()
    except Exception as e:
        log.warning("sim_db_update_failed", error=str(e)[:300])
        return None


def _fetch(sql: str, params: tuple) -> list[tuple]:
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def schedule_memory_cleanup(simulation_id: str) -> None:
    """Accoda la cancellazione della memoria degli agenti di una simulazione appena chiusa.

    Nessuno la legge dopo i round (report e chat usano la persona). Non blocca chi chiude: se non si
    riesce ad accodare, la collection la cancella la passata all'avvio del worker.
    """
    try:
        from celery import current_app
        current_app.send_task(MEMORY_CLEANUP_TASK, args=[simulation_id])
    except Exception as e:
        log.warning("memory_cleanup_schedule_failed", simulation_id=simulation_id, error=str(e)[:300])


def enter_phase(simulation_id: str, status: str, task_id: str | None) -> bool:
    """Registra fase e task corrente. False se la simulazione e' gia' chiusa: il task non deve partire."""
    rows = _execute(
        f"UPDATE simulations SET status=%s, celery_task_id=COALESCE(%s, celery_task_id) "
        f"WHERE id=%s AND {_NOT_CLOSED}",
        (status, task_id, simulation_id),
    )
    return rows != 0


def abort_redelivered_run(simulation_id: str, task_id: str | None, redelivered_flag: bool = False) -> bool:
    """Chiude un run_simulation riconsegnato da Celery dopo un riavvio del worker. True se l'ha chiuso.

    Nel flusso normale il run entra con la simulazione in SPAWNING_AGENTS: se la trova gia' RUNNING
    con un orario di partenza, il run precedente e' morto con il worker e questo messaggio lo
    farebbe ripartire dal round 1 senza dirlo a nessuno. Invece: FAILED con un messaggio chiaro,
    quota restituita con le regole di sempre (refund_quota) e simulation_redelivered_aborted nei log.
    """
    rows = _execute(
        "UPDATE simulations SET status='FAILED', error_message=%s, error_detail=%s "
        "WHERE id=%s AND status='RUNNING' AND started_at IS NOT NULL",
        (*_stored(_REDELIVERED), simulation_id),
    )
    if not rows:
        return False
    log.error("simulation_redelivered_aborted", simulation_id=simulation_id, task_id=task_id,
              redelivered_flag=redelivered_flag)
    refund_quota(simulation_id, REFUND_REASON_WORKER_RESTART)
    schedule_memory_cleanup(simulation_id)
    return True


def record_round(simulation_id: str, current_round: int, total_posts: int) -> bool:
    """Salva l'avanzamento. False se la simulazione non e' piu' in corso (es. fermata dall'utente)."""
    rows = _execute(
        "UPDATE simulations SET current_round=%s, total_posts=%s WHERE id=%s AND status='RUNNING'",
        (current_round, total_posts, simulation_id),
    )
    return rows != 0


def finish_rounds(simulation_id: str, current_round: int, total_posts: int) -> None:
    _execute(
        "UPDATE simulations SET status='GENERATING_REPORT', current_round=%s, total_posts=%s "
        "WHERE id=%s AND status='RUNNING'",
        (current_round, total_posts, simulation_id),
    )


def mark_completed(simulation_id: str) -> None:
    rows = _execute(
        "UPDATE simulations SET status='COMPLETED', completed_at=(now() AT TIME ZONE 'utc') "
        "WHERE id=%s AND status='GENERATING_REPORT'",
        (simulation_id,),
    )
    if rows:
        log.info("sim_status_updated", simulation_id=simulation_id, status="COMPLETED")
        schedule_memory_cleanup(simulation_id)


def record_failure(phase: str, resource_id: str, exc: BaseException) -> None:
    """Il grafo appartiene al progetto, le altre fasi alla simulazione."""
    message, detail = _stored(failure_detail(phase, exc))
    if phase == PHASE_GRAPH:
        rows = _execute(
            "UPDATE projects SET graph_error=%s, graph_error_detail=%s "
            "WHERE id=%s AND graph_built IS NOT TRUE AND graph_error IS NULL",
            (message, detail, resource_id),
        )
    else:
        rows = _execute(
            f"UPDATE simulations SET status='FAILED', error_message=%s, error_detail=%s "
            f"WHERE id=%s AND {_NOT_CLOSED}",
            (message, detail, resource_id),
        )
    if rows:
        # Celery riduce le eccezioni non picklabili degli SDK alla classe base: il tipo esatto resta qui
        log.error("task_failure_recorded", phase=phase, resource_id=resource_id,
                  error_type=type(exc).__name__, error_message=message)
        # Solo chi ha chiuso la riga restituisce la quota: il segnale task_failure che arriva dopo trova rows == 0
        if phase != PHASE_GRAPH and phase in _REFUND_PHASES:
            refund_quota(resource_id, f"{phase}_failed",
                         credential_failure=getattr(exc, "status_code", None) in _CREDENTIAL_STATUSES)
        if phase != PHASE_GRAPH:
            schedule_memory_cleanup(resource_id)


def record_rebuild_failure(project_id: str, exc: BaseException) -> None:
    """Ricostruzione fallita con il grafo precedente rimesso in uso: il progetto resta utilizzabile.

    graph_built torna TRUE e graph_error spiega perche' la ricostruzione non e' riuscita.
    """
    message, detail = _stored({"key": "rebuild_failed", "params": {"reason": _failure_reason(exc)}})
    rows = _execute(
        "UPDATE projects SET graph_built=TRUE, graph_error=%s, graph_error_detail=%s WHERE id=%s",
        (message, detail, project_id),
    )
    log.error("graph_rebuild_failed", project_id=project_id, error_type=type(exc).__name__,
              error_message=message, previous_graph_restored=True, rows=rows)


def refund_quota(simulation_id: str, reason: str, credential_failure: bool = False) -> bool:
    """Restituisce al contatore mensile dell'utente una simulazione FAILED. Mai due volte.

    I fallimenti per chiave o modello dell'utente (401/403/404 con una credenziale dell'utente) si
    restituiscono fino a CREDENTIAL_REFUNDS_PER_MONTH al mese, contati sul mese di creazione;
    oltre si registra quota_refund_capped. Con la chiave di sistema il problema non e' dell'utente:
    rimborso normale. Una simulazione creata prima di usage_reset_at appartiene a un periodo gia'
    azzerato: non si rimborsa (quota_refund_skipped), per non scalare il periodo nuovo.
    True se la quota e' stata restituita.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, created_at, llm_credential_id FROM simulations "
                    "WHERE id=%s AND status='FAILED' AND quota_refunded IS NOT TRUE",
                    (simulation_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                user_id, created_at, credential_id = row
                # Un rimborso alla volta per utente: il tetto conta i rimborsi gia' fatti
                cur.execute(
                    "SELECT id, usage_reset_at FROM subscriptions WHERE user_id=%s FOR UPDATE", (user_id,)
                )
                subscription = cur.fetchone()
                has_subscription = subscription is not None
                usage_reset_at = subscription[1] if subscription else None
                if usage_reset_at is not None and created_at is not None and created_at < usage_reset_at:
                    log.info("quota_refund_skipped", user_id=user_id, simulation_id=simulation_id,
                             reason=reason, skip_reason="previous_period",
                             created_at=created_at.isoformat(), usage_reset_at=usage_reset_at.isoformat())
                    return False
                cur.execute(
                    "SELECT quota_refunded FROM simulations WHERE id=%s FOR UPDATE", (simulation_id,)
                )
                if cur.fetchone()[0]:
                    return False
                if credential_failure and credential_id:
                    reason = REFUND_REASON_CREDENTIAL
                    cur.execute(
                        "SELECT count(*) FROM simulations WHERE user_id=%s AND quota_refund_reason=%s "
                        "AND date_trunc('month', created_at) = date_trunc('month', %s::timestamp)",
                        (user_id, REFUND_REASON_CREDENTIAL, created_at),
                    )
                    used = cur.fetchone()[0]
                    if used >= CREDENTIAL_REFUNDS_PER_MONTH:
                        log.warning("quota_refund_capped", user_id=user_id, simulation_id=simulation_id,
                                    reason=reason, refunds_this_month=used, cap=CREDENTIAL_REFUNDS_PER_MONTH)
                        return False
                cur.execute(
                    "UPDATE simulations SET quota_refunded=TRUE, quota_refund_reason=%s WHERE id=%s",
                    (reason, simulation_id),
                )
                if has_subscription:
                    cur.execute(
                        "UPDATE subscriptions SET simulations_used_this_month = "
                        "GREATEST(COALESCE(simulations_used_this_month, 0) - 1, 0) WHERE user_id=%s",
                        (user_id,),
                    )
        finally:
            conn.close()
    except Exception as e:
        log.warning("quota_refund_failed", simulation_id=simulation_id, reason=reason, error=str(e)[:300])
        return False
    log.info("quota_refunded", user_id=user_id, simulation_id=simulation_id, reason=reason,
             subscription_found=has_subscription)
    return True


def _first_args(entries: list[dict]) -> set[str]:
    ids = set()
    for entry in entries:
        args = entry.get("args")
        if not isinstance(args, (list, tuple)):
            raise ValueError(f"unexpected task args: {type(args).__name__}")
        if args:
            ids.add(str(args[0]))
    return ids


def _queued_ids(app) -> set[str]:
    """Primo argomento dei task ancora in coda su Redis, che i worker non vedono."""
    import redis
    client = redis.from_url(app.conf.broker_url)
    ids = set()
    for raw in client.lrange(app.conf.task_default_queue, 0, -1):
        message = json.loads(raw)
        args = json.loads(base64.b64decode(message["body"]))[0]
        if args:
            ids.add(str(args[0]))
    return ids


def _unacked_ids(app) -> set[str]:
    """Primo argomento dei task consegnati e non confermati: quelli di un worker morto restano qui
    finche' Redis non li riconsegna (al riavvio o dopo il visibility timeout)."""
    import redis
    client = redis.from_url(app.conf.broker_url)
    ids = set()
    for raw in client.hvals("unacked"):
        message = json.loads(raw)[0]
        args = json.loads(base64.b64decode(message["body"]))[0]
        if args:
            ids.add(str(args[0]))
    return ids


def busy_resource_ids(app) -> set[str] | None:
    """Id di simulazioni e progetti con un task vivo: attivo, riservato, programmato, in coda o
    consegnato e in attesa di riconsegna. None se non si riesce a stabilirlo."""
    try:
        inspector = app.control.inspect(timeout=2)
        active = inspector.active()
        reserved = inspector.reserved()
        scheduled = inspector.scheduled()
        if not active or reserved is None or scheduled is None:
            return None
        ids = _queued_ids(app) | _unacked_ids(app)
        for tasks in active.values():
            ids |= _first_args(tasks)
        for tasks in reserved.values():
            ids |= _first_args(tasks)
        for tasks in scheduled.values():
            ids |= _first_args([t["request"] for t in tasks])
        return ids
    except Exception as e:
        log.warning("busy_resources_unknown", error=str(e)[:300])
        return None


def reap_stale(busy_ids, older_than_minutes: int, graph_exists) -> dict | None:
    """Chiude le righe ancora "in corso" da oltre N minuti e senza un task vivo.

    busy_ids() ritorna gli id con un task vivo, o None se Celery non risponde: si chiama all'inizio e
    di nuovo subito prima di chiudere ogni simulazione, perche' nel frattempo un task puo' essere
    partito, accodato o riconsegnato. None se Celery non risponde all'inizio.
    """
    busy = busy_ids()
    if busy is None:
        return None
    # LOCALTIMESTAMP come le colonne, che sono senza fuso e scritte nel fuso della sessione
    rows = _fetch(
        "SELECT id, status, COALESCE(started_at, created_at) FROM simulations "
        "WHERE status::text = ANY(%s) "
        "AND COALESCE(started_at, created_at) < LOCALTIMESTAMP - make_interval(mins => %s)",
        (list(RUNNING_STATUSES), older_than_minutes),
    )
    simulations = []
    for simulation_id, status, since in rows:
        if simulation_id in busy:
            continue
        fresh = busy_ids()
        if fresh is None or simulation_id in fresh:
            log.info("stale_simulation_kept", simulation_id=simulation_id, status=status,
                     reason="celery_unknown" if fresh is None else "task_alive")
            continue
        updated = _execute(
            "UPDATE simulations SET status='FAILED', error_message=%s, error_detail=%s "
            "WHERE id=%s AND status=%s",
            (*_stored(_STALE_SIMULATION), simulation_id, status),
        )
        if updated:
            simulations.append(simulation_id)
            log.warning("stale_simulation_failed", simulation_id=simulation_id, status=status, since=str(since))
            # Ferma durante il report: i round ci sono, come per un report fallito niente rimborso
            if str(status) in _REFUND_STALE_STATUSES:
                refund_quota(simulation_id, REFUND_REASON_STALE)
            schedule_memory_cleanup(simulation_id)

    projects = []
    for project_id, since in _fetch(
        "SELECT id, created_at FROM projects "
        "WHERE graph_built IS NOT TRUE AND graph_error IS NULL AND graph_task_id IS NOT NULL "
        "AND created_at < LOCALTIMESTAMP - make_interval(mins => %s)",
        (older_than_minutes,),
    ):
        if project_id in busy or graph_exists(project_id):
            continue
        updated = _execute(
            "UPDATE projects SET graph_error=%s, graph_error_detail=%s "
            "WHERE id=%s AND graph_built IS NOT TRUE AND graph_error IS NULL",
            (*_stored(_STALE_GRAPH), project_id),
        )
        if updated:
            projects.append(project_id)
            log.warning("stale_graph_failed", project_id=project_id, since=str(since))

    return {"simulations": simulations, "projects": projects}
