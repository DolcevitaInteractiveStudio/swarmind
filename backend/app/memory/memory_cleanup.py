"""
Pulizia delle collection di memoria degli agenti su Chroma.

Nessuno legge la memoria di una simulazione dopo i round: il report e la chat con gli agenti usano
i campi della persona salvati in agents.json. Quindi la collection si cancella appena la simulazione
arriva a uno stato finale (COMPLETED dopo il report, FAILED, STOPPED), senza periodo di retention:

  - delete_simulation_memory: la cancellazione, lanciata dal task swarmind.delete_simulation_memory
    che lifecycle e lo stop accodano quando chiudono una simulazione;
  - sweep_closed_memory_collections: all'avvio del worker riprende le cancellazioni non riuscite
    (Chroma giu', worker riavviato), solo per collection sim_<id>_memory di simulazioni che il DB
    dice chiuse. Quelle di simulazioni che nel DB non ci sono le lascia: le toglie chroma-cleanup;
  - flask chroma-cleanup: comando una tantum per le collection sim_* esistenti, anche quelle per
    agente (sim_<id>_agent_<id>) di prima. Mai le kb_*. Vedi docs/runbooks/chroma-cleanup.md.
"""
from __future__ import annotations

import sys
import time

import click
import structlog

from ..simulation import lifecycle
from .agent_memory import forget_simulation_collection, memory_collection_name
from .chroma_client import error_text, get_chroma

log = structlog.get_logger()

FINAL_STATUSES = ("COMPLETED", "FAILED", "STOPPED")
# Simulazioni che possono ancora scrivere memoria: le loro collection non si toccano mai
ACTIVE_STATUSES = ("PENDING",) + tuple(lifecycle.RUNNING_STATUSES)

KIND_MEMORY = "memory"  # sim_<id>_memory, una per simulazione
KIND_AGENT = "agent"    # sim_<id>_agent_<agent_id>, una per agente (fino a novembre 2026)

_MEMORY_SUFFIX = "_memory"
_AGENT_MARKER = "_agent_"

DEFAULT_BATCH_SIZE = 10
DEFAULT_PAUSE_SECONDS = 2.0


def parse_collection_name(name: str) -> tuple[str, str] | None:
    """(simulation_id, kind) per una collection di memoria, None per tutte le altre (kb_* comprese)."""
    if not name.startswith("sim_"):
        return None
    rest = name[len("sim_"):]
    if _AGENT_MARKER in rest:
        simulation_id = rest.split(_AGENT_MARKER, 1)[0]
        return (simulation_id, KIND_AGENT) if simulation_id else None
    if rest.endswith(_MEMORY_SUFFIX) and len(rest) > len(_MEMORY_SUFFIX):
        return rest[: -len(_MEMORY_SUFFIX)], KIND_MEMORY
    return None


def simulation_statuses(simulation_ids) -> dict[str, str]:
    """Stato delle simulazioni nel DB. Le simulazioni che non ci sono non compaiono. Solleva se il DB non risponde."""
    ids = sorted(set(simulation_ids))
    if not ids:
        return {}
    rows = lifecycle._fetch("SELECT id, status::text FROM simulations WHERE id = ANY(%s)", (ids,))
    return {str(sim_id): str(status) for sim_id, status in rows}


def delete_simulation_memory(simulation_id: str) -> bool:
    """Cancella la collection di memoria della simulazione. True se c'era ed e' stata cancellata."""
    from chromadb.errors import NotFoundError

    name = memory_collection_name(simulation_id)
    started = time.monotonic()
    try:
        get_chroma().delete_collection(name=name)
    except NotFoundError:
        log.info("memory_collection_absent", simulation_id=simulation_id, collection=name)
        return False
    except ValueError as e:
        # chromadb 1.0.21 segnala cosi' la collection che non esiste
        if "does not exist" not in str(e):
            raise
        log.info("memory_collection_absent", simulation_id=simulation_id, collection=name)
        return False
    finally:
        forget_simulation_collection(simulation_id)
    log.info("memory_collection_deleted", simulation_id=simulation_id, collection=name,
             ms=round((time.monotonic() - started) * 1000))
    return True


def delete_if_closed(simulation_id: str) -> str:
    """Cancella la memoria solo se il DB dice che la simulazione e' chiusa. Ritorna l'esito."""
    try:
        status = simulation_statuses([simulation_id]).get(simulation_id)
    except Exception as e:
        log.warning("memory_collection_delete_skipped", simulation_id=simulation_id,
                    reason="db_unavailable", error=error_text(e))
        return "skipped"
    if status not in FINAL_STATUSES:
        log.warning("memory_collection_delete_skipped", simulation_id=simulation_id,
                    reason="not_closed", status=status)
        return "skipped"
    try:
        return "deleted" if delete_simulation_memory(simulation_id) else "absent"
    except Exception as e:
        # La riprende la passata all'avvio del worker
        log.warning("memory_collection_delete_failed", simulation_id=simulation_id,
                    collection=memory_collection_name(simulation_id), error=error_text(e))
        return "failed"


def sweep_closed_memory_collections() -> dict:
    """Cancella le collection sim_<id>_memory di simulazioni che il DB dice chiuse.

    Una simulazione che nel DB non c'e' puo' essere un run fuori dall'app (CLI, test) ancora in
    corso: la passata automatica non la tocca e la conta tra le orfane. Le orfane e le collection per
    agente le toglie il comando chroma-cleanup, dopo il dry run.
    """
    names = [c.name for c in get_chroma().list_collections()]
    memory = {}
    for name in names:
        parsed = parse_collection_name(name)
        if parsed and parsed[1] == KIND_MEMORY:
            memory[parsed[0]] = name
    statuses = simulation_statuses(memory)
    result = {"deleted": [], "kept": 0, "orphans": 0, "failed": 0}
    for simulation_id in sorted(memory):
        status = statuses.get(simulation_id)
        if status not in FINAL_STATUSES:
            result["kept"] += 1
            result["orphans"] += status is None
            continue
        try:
            if delete_simulation_memory(simulation_id):
                result["deleted"].append(simulation_id)
        except Exception as e:
            result["failed"] += 1
            log.warning("memory_collection_delete_failed", simulation_id=simulation_id,
                        collection=memory[simulation_id], error=error_text(e))
    log.info("memory_sweep_done", deleted=len(result["deleted"]), kept=result["kept"],
             orphans=result["orphans"], failed=result["failed"], collections=len(names))
    return result


def plan_cleanup(names: list[str], statuses: dict[str, str]) -> dict:
    """Divide le collection: da cancellare (sim_* di simulazioni chiuse o sparite dal DB), protette
    (simulazioni attive), non riconosciute (sim_* con un nome inatteso) e il resto (kb_* e altre)."""
    plan = {"delete": [], "protected": [], "unrecognized": [], "other": []}
    for name in sorted(names):
        parsed = parse_collection_name(name)
        if parsed is None:
            plan["unrecognized" if name.startswith("sim_") else "other"].append(name)
            continue
        simulation_id, kind = parsed
        status = statuses.get(simulation_id)
        entry = {"name": name, "simulation_id": simulation_id, "kind": kind, "status": status or "missing"}
        plan["protected" if status in ACTIVE_STATUSES else "delete"].append(entry)
    return plan


@click.command("chroma-cleanup")
@click.option("--dry-run", is_flag=True, help="Elenca cosa verrebbe cancellato, senza cancellare.")
@click.option("--batch-size", default=DEFAULT_BATCH_SIZE, show_default=True, type=click.IntRange(1, 100),
              help="Collection cancellate per batch.")
@click.option("--pause", default=DEFAULT_PAUSE_SECONDS, show_default=True, type=click.FloatRange(0, 60),
              help="Secondi di pausa tra un batch e l'altro.")
def chroma_cleanup_command(dry_run: bool, batch_size: int, pause: float):
    """Cancella le collection di memoria degli agenti (sim_*) di simulazioni non attive. Mai le kb_*."""
    client = get_chroma()
    names = [c.name for c in client.list_collections()]
    ids = {parsed[0] for parsed in map(parse_collection_name, names) if parsed}
    try:
        statuses = simulation_statuses(ids)
    except Exception as e:
        # Senza lo stato non si sa quali simulazioni sono attive: non si cancella niente
        click.echo(f"ERROR: database not reachable, nothing deleted: {error_text(e)}", err=True)
        sys.exit(2)
    plan = plan_cleanup(names, statuses)
    kb = [n for n in plan["other"] if n.startswith("kb_")]
    click.echo(f"collections: {len(names)} total, {len(kb)} kb_*, {len(plan['delete'])} sim_* to delete, "
               f"{len(plan['protected'])} sim_* protected (active simulation), "
               f"{len(plan['unrecognized'])} sim_* unrecognized (kept), "
               f"{len(plan['other']) - len(kb)} other (kept)")
    for entry in plan["protected"]:
        click.echo(f"  keep    {entry['name']}  (simulation {entry['status']})")
    for name in plan["unrecognized"]:
        click.echo(f"  keep    {name}  (unrecognized name)")
    if dry_run:
        for entry in plan["delete"]:
            click.echo(f"  delete  {entry['name']}  ({entry['kind']}, simulation {entry['status']})")
        click.echo("dry run: nothing deleted")
        return

    deleted = failed = 0
    batch = plan["delete"]
    for start in range(0, len(batch), batch_size):
        if start:
            time.sleep(pause)
        for entry in batch[start:start + batch_size]:
            name = entry["name"]
            # Doppia sicurezza: solo collection di memoria, mai la KB
            assert name.startswith("sim_") and not name.startswith("kb_"), name
            try:
                client.delete_collection(name=name)
            except Exception as e:
                failed += 1
                log.warning("chroma_cleanup_failed", collection=name, error=error_text(e))
                click.echo(f"  FAILED  {name}: {error_text(e)}")
                continue
            deleted += 1
            log.info("chroma_cleanup_deleted", collection=name, simulation_id=entry["simulation_id"],
                     kind=entry["kind"], simulation_status=entry["status"])
            click.echo(f"  deleted {name}")
        click.echo(f"batch done: {deleted} deleted, {failed} failed, {len(batch) - deleted - failed} left")
    remaining = [c.name for c in client.list_collections()]
    click.echo(f"done: {deleted} deleted, {failed} failed; collections now {len(remaining)} "
               f"({len([n for n in remaining if n.startswith('kb_')])} kb_*, "
               f"{len([n for n in remaining if n.startswith('sim_')])} sim_*)")
    log.info("chroma_cleanup_done", deleted=deleted, failed=failed, collections_after=len(remaining))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    chroma_cleanup_command()
