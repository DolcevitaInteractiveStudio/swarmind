"""
/api/graph — Knowledge Graph

POST /api/graph/upload          → carica documento e avvia build
GET  /api/graph/<project_id>    → stato e dati del grafo
GET  /api/graph/<project_id>/nodes → nodi per visualizzazione D3
POST /api/graph/<project_id>/rebuild → ricostruisce il grafo dal file sorgente (chiamate LLM)
"""
import os
import shutil
import uuid

from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.utils import secure_filename

from app.core.i18n import api_error
from app.models import db, Project, AuditLog
from app.utils.state_store import StateStore
from .auth import login_required, plan_required

graph_bp = Blueprint("graph", __name__)

ALLOWED_EXT = {".pdf", ".txt", ".md", ".docx", ".json", ".csv"}


def _store() -> StateStore:
    return StateStore(current_app.config["SIMULATIONS_DIR"])


# ── Graph builds on the system key ─────────────────────────────────────────────
# A user with a provider key of their own builds graphs with it. Without one, the build runs on the shared
# system key (GROQ_API_KEY), at most GRAPH_SYSTEM_KEY_MONTHLY_LIMIT times per quota period. Before, those builds
# were not counted anywhere.

def _use_own_credential(user_id: str, provider: str | None, models: dict) -> tuple[str | None, str | None, dict]:
    """(provider, credential_id, models) of the user's own key for a build without a credential, or
    (provider, None, models) if the user has none. Models chosen for another provider are dropped."""
    from app.core.llm_router import own_credential
    cred = own_credential(user_id, provider)
    if cred is None:
        return provider, None, models
    if provider and provider != cred.provider:
        models = {k: None for k in models}
    return cred.provider, cred.id, models


def _reserve_system_graph_build(sub) -> bool:
    """Counts a graph build on the system key in the current quota period, only if there is room. Atomic.

    One UPDATE with the limit in its WHERE, like the simulation quota (api/simulation._reserve_quota): two
    builds at the same time do not lose an increment nor go over the limit. A counter of an earlier period
    starts again from 1. False when the limit is reached (or is 0)."""
    from sqlalchemy import and_, case, func, or_, update
    from app.models import Subscription
    from app.models.usage_period import to_db

    limit = int(current_app.config.get("GRAPH_SYSTEM_KEY_MONTHLY_LIMIT", 20))
    if limit == 0:
        return False
    period = to_db(sub.usage_period_start())
    used = func.coalesce(Subscription.graph_system_builds_used, 0)
    same_period = and_(Subscription.graph_system_builds_period.isnot(None),
                       Subscription.graph_system_builds_period >= period)
    stmt = (update(Subscription).where(Subscription.id == sub.id)
            .values(graph_system_builds_used=case((same_period, used + 1), else_=1),
                    graph_system_builds_period=period)
            .execution_options(synchronize_session=False))
    if limit > 0:
        stmt = stmt.where(or_(~same_period, used < limit))
    reserved = db.session.execute(stmt).rowcount == 1
    db.session.expire(sub, ["graph_system_builds_used", "graph_system_builds_period"])
    return reserved


def _release_system_graph_build(sub) -> None:
    """Gives back a reserved build whose task could not be queued."""
    from sqlalchemy import case, func, update
    from app.models import Subscription
    used = func.coalesce(Subscription.graph_system_builds_used, 0)
    db.session.execute(update(Subscription).where(Subscription.id == sub.id)
                       .values(graph_system_builds_used=case((used > 0, used - 1), else_=0))
                       .execution_options(synchronize_session=False))
    db.session.expire(sub, ["graph_system_builds_used"])


def _system_graph_limit_error():
    limit = int(current_app.config.get("GRAPH_SYSTEM_KEY_MONTHLY_LIMIT", 20))
    return jsonify({"error": api_error("graph_system_key_limit", limit=limit),
                    "code": "graph_system_key_limit"}), 403


@graph_bp.post("/upload")
@login_required
def upload_document():
    user = g.current_user
    sub = user.subscription
    if not sub:
        return jsonify({"error": api_error("no_active_plan")}), 403

    # Controlla limite progetti
    max_p = sub.plan.max_projects
    if max_p != -1 and Project.query.filter_by(user_id=user.id).count() >= max_p:
        return jsonify({"error": api_error("project_limit", max=max_p)}), 403

    # No system key and no credential: the graph build would fail with HTTP 401 after the upload
    from app.core.llm_router import user_has_llm_access
    if not user_has_llm_access(user.id):
        return jsonify({"error": api_error("no_llm_provider"), "code": "no_llm_provider"}), 400

    if "file" not in request.files:
        return jsonify({"error": api_error("no_file")}), 400

    file = request.files["file"]
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": api_error("unsupported_format", formats=", ".join(ALLOWED_EXT))}), 400

    # Controlla dimensione file
    max_mb = sub.plan.max_file_size_mb
    file.seek(0, 2)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > max_mb:
        return jsonify({"error": api_error("file_too_large", size=f"{size_mb:.1f}", max=max_mb)}), 413

    project_id = str(uuid.uuid4())[:12]
    safe_name = secure_filename(file.filename)
    upload_dir = os.path.join(current_app.config["UPLOADS_DIR"], project_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, safe_name)
    file.save(file_path)

    sim_topic = request.form.get("topic", "Analisi generale")
    name = request.form.get("name", safe_name)

    # Leggi config LLM dal form (opzionali — fallback a Groq di sistema se vuoti)
    llm_provider = request.form.get("llm_provider") or None
    llm_credential_id = request.form.get("llm_credential_id") or None
    model_heavy = request.form.get("model_heavy") or None
    model_agent = request.form.get("model_agent") or None
    model_fast = request.form.get("model_fast") or None

    # Se l'utente ha scelto una credenziale, verifica che gli appartenga
    if llm_credential_id:
        from app.models import LLMCredential
        cred = LLMCredential.query.filter_by(
            id=llm_credential_id, user_id=user.id, is_active=True
        ).first()
        if not cred:
            return jsonify({"error": api_error("invalid_credential")}), 400
        # Forza coerenza provider <-> credenziale
        if llm_provider and llm_provider != cred.provider:
            return jsonify({"error": api_error("provider_mismatch")}), 400
        llm_provider = cred.provider
    else:
        # No credential chosen: the user's own key if there is one, the system key only within its limit
        models = {"heavy": model_heavy, "agent": model_agent, "fast": model_fast}
        llm_provider, llm_credential_id, models = _use_own_credential(user.id, llm_provider, models)
        model_heavy, model_agent, model_fast = models["heavy"], models["agent"], models["fast"]
    from app.core.llm_router import system_key_configured
    if not llm_credential_id and system_key_configured() and not _reserve_system_graph_build(sub):
        db.session.rollback()
        shutil.rmtree(upload_dir, ignore_errors=True)
        return _system_graph_limit_error()

    # Salva progetto nel DB
    project = Project(
        id=project_id,
        user_id=user.id,
        name=name,
        description=request.form.get("description", ""),
        source_filename=safe_name,
        source_file_path=file_path,
        llm_provider=llm_provider,
        llm_credential_id=llm_credential_id,
        model_heavy=model_heavy,
        model_agent=model_agent,
        model_fast=model_fast,
    )
    db.session.add(project)
    db.session.commit()

    # Lancia task asincrono
    from app.simulation.tasks import build_graph_task
    task = build_graph_task.delay(project_id, file_path, sim_topic)
    project.graph_task_id = task.id
    db.session.commit()

    AuditLog.log("graph_build_started", user_id=user.id,
                 resource_type="project", resource_id=project_id)

    return jsonify({
        "project_id": project_id,
        "task_id": task.id,
        "status": "building",
    }), 202


@graph_bp.get("/<string:project_id>")
@login_required
def get_graph(project_id: str):
    project = Project.query.filter_by(
        id=project_id, user_id=g.current_user.id
    ).first_or_404()

    # Controlla stato task — usa il file salvato dal worker come fonte di verità
    # (evita dipendenza da AsyncResult/result_backend)
    if project.graph_task_id and not project.graph_built:
        graph_file_exists = False
        try:
            graph_data_check = _store().load_graph(project_id)
            graph_file_exists = bool(graph_data_check)
        except (FileNotFoundError, Exception):
            graph_file_exists = False

        if graph_file_exists:
            # Il worker ha salvato il grafo — aggiorna il DB
            project.graph_built = True
            project.num_entities = len(graph_data_check.get("nodes", []))
            project.num_relations = len(graph_data_check.get("edges", []))
            project.graph_error = None
            project.graph_error_detail = None
            db.session.commit()
        elif project.graph_error:
            return jsonify({
                "project": project.to_dict(),
                "task_state": "FAILED",
                "phase": "graph",
            }), 200
        else:
            # Grafo non ancora pronto
            return jsonify({
                "project": project.to_dict(),
                "task_state": "PROGRESS",
                "phase": "graph",
            }), 200

    # Carica dati grafo da disco
    store = _store()
    try:
        graph_data = store.load_graph(project_id)
    except FileNotFoundError:
        graph_data = {}

    return jsonify({
        "project": project.to_dict(),
        "task_state": "completed" if project.graph_built else "pending",
        "graph": graph_data,
    }), 200


@graph_bp.post("/<string:project_id>/rebuild")
@login_required
def rebuild_graph(project_id: str):
    """Ricostruisce il grafo dal file sorgente con il parser attuale, stesso id progetto.

    Solo su richiesta dell'utente: usa chiamate LLM. La KB non si tocca (si ricostruisce allo spawn).
    Il grafo in uso resta da parte finche' il nuovo non e' pronto e torna se la ricostruzione fallisce.
    """
    from app.models import Simulation, SimulationStatus
    from app.simulation.tasks import build_graph_task

    user = g.current_user
    project = Project.query.filter_by(id=project_id, user_id=user.id).first_or_404()

    if project.graph_task_id and not project.graph_built and not project.graph_error:
        return jsonify({"error": api_error("graph_building")}), 409
    # Spawn e round leggono il grafo dal disco: non va spostato mentre girano
    busy = project.simulations.filter(Simulation.status.in_([
        SimulationStatus.BUILDING_GRAPH, SimulationStatus.SPAWNING_AGENTS, SimulationStatus.RUNNING,
    ])).count()
    if busy:
        return jsonify({"error": api_error("simulations_running")}), 409
    if not project.source_file_path or not os.path.exists(project.source_file_path):
        return jsonify({"error": api_error("source_missing")}), 400

    # The build uses the project's credential if still active, else the user's own key, else the system key
    # within its monthly limit
    from app.core.llm_router import system_key_configured
    from app.models import LLMCredential
    has_credential = bool(project.llm_provider and project.llm_credential_id and LLMCredential.query.filter_by(
        id=project.llm_credential_id, user_id=user.id, is_active=True).first())
    on_system_key = False
    if not has_credential:
        models = {"heavy": project.model_heavy, "agent": project.model_agent, "fast": project.model_fast}
        provider, credential_id, models = _use_own_credential(user.id, project.llm_provider, models)
        if credential_id:
            project.llm_provider, project.llm_credential_id = provider, credential_id
            project.model_heavy, project.model_agent, project.model_fast = (
                models["heavy"], models["agent"], models["fast"])
        elif system_key_configured():
            if not user.subscription or not _reserve_system_graph_build(user.subscription):
                db.session.rollback()
                return _system_graph_limit_error()
            on_system_key = True

    store = _store()
    had_graph = store.set_aside_graph(project_id)
    was_built, old_error, old_detail = project.graph_built, project.graph_error, project.graph_error_detail
    project.graph_built = False
    project.graph_error = None
    project.graph_error_detail = None
    db.session.commit()
    try:
        task = build_graph_task.apply_async(
            args=[project_id, project.source_file_path, project.name], kwargs={"rebuild": True}
        )
    except Exception:
        # Coda irraggiungibile: tutto come prima
        if had_graph:
            store.restore_previous_graph(project_id)
        project.graph_built, project.graph_error, project.graph_error_detail = was_built, old_error, old_detail
        if on_system_key:
            _release_system_graph_build(user.subscription)
        db.session.commit()
        current_app.logger.exception("graph_rebuild_enqueue_failed")
        return jsonify({"error": api_error("rebuild_unavailable")}), 503
    project.graph_task_id = task.id
    db.session.commit()

    AuditLog.log("graph_rebuild_started", user_id=user.id, resource_type="project", resource_id=project_id,
                 details={"had_graph": had_graph})
    return jsonify({"project_id": project_id, "task_id": task.id, "status": "building"}), 202


@graph_bp.get("/<string:project_id>/nodes")
@login_required
def get_nodes(project_id: str):
    """Restituisce nodi e archi per la visualizzazione D3."""
    Project.query.filter_by(
        id=project_id, user_id=g.current_user.id
    ).first_or_404()

    store = _store()
    try:
        data = store.load_graph(project_id)
    except FileNotFoundError:
        return jsonify({"nodes": [], "edges": []}), 200

    # Semplifica per D3
    nodes = [
        {"id": n["id"], "label": n.get("label", n["id"]),
         "type": n.get("type", "UNKNOWN"), "group": n.get("community", 0)}
        for n in data.get("nodes", [])[:300]  # max 300 nodi per rendering
    ]
    edges = [
        {"source": e["from"], "target": e["to"],
         "value": e.get("weight", 0.5)}
        for e in data.get("edges", [])[:500]
    ]
    return jsonify({"nodes": nodes, "edges": edges, "stats": data.get("stats", {})}), 200


@graph_bp.get("/projects")
@login_required
def list_projects():
    projects = Project.query.filter_by(user_id=g.current_user.id)\
        .order_by(Project.created_at.desc()).all()
    return jsonify([p.to_dict() for p in projects]), 200


@graph_bp.delete("/<string:project_id>")
@login_required
def delete_project(project_id: str):
    project = Project.query.filter_by(
        id=project_id, user_id=g.current_user.id
    ).first_or_404()
    db.session.delete(project)
    db.session.commit()
    return jsonify({"ok": True}), 200
