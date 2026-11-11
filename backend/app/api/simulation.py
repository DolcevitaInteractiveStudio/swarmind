"""
/api/simulation

POST /api/simulation/create          → crea simulazione (sceglie provider LLM)
POST /api/simulation/<id>/start      → avvia spawn agenti + loop
GET  /api/simulation/<id>/status     → stato corrente + metriche
GET  /api/simulation/<id>/feed       → ultimi post del social feed
POST /api/simulation/<id>/stop       → ferma la simulazione
GET  /api/simulation/list            → tutte le simulazioni dell'utente
"""
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from sqlalchemy import func, update

from app.core.i18n import SUPPORTED_LANGUAGES, api_error, configured_default_language, normalize_language, t
from app.models import db, Project, Simulation, SimulationStatus, AuditLog, Subscription
from app.utils.state_store import StateStore
from flask import current_app
from .auth import login_required

sim_bp = Blueprint("simulation", __name__)


def _store():
    return StateStore(current_app.config["SIMULATIONS_DIR"])


def _reserve_quota(sub) -> bool:
    """Conta una simulazione nella quota del mese, solo se c'e' ancora posto. Atomico.

    Un solo UPDATE con il controllo del limite: due creazioni simultanee non perdono un incremento
    e non superano il piano. La riga resta bloccata fino al commit della richiesta, come fanno il
    reset del periodo (Subscription.refresh_usage_period, FOR UPDATE) e il rimborso
    (lifecycle.refund_quota). False se la quota e' esaurita.
    """
    used = func.coalesce(Subscription.simulations_used_this_month, 0)
    stmt = (update(Subscription).where(Subscription.id == sub.id)
            .values(simulations_used_this_month=used + 1)
            .execution_options(synchronize_session=False))
    limit = sub.plan.max_simulations_per_month
    if limit != -1:
        stmt = stmt.where(used < limit)
    reserved = db.session.execute(stmt).rowcount == 1
    db.session.expire(sub, ["simulations_used_this_month"])
    return reserved


@sim_bp.post("/create")
@login_required
def create_simulation():
    user = g.current_user
    sub = user.subscription
    if not sub or not sub.has_quota():
        return jsonify({
            "error": api_error("quota_exhausted"),
            "upgrade_url": "/pricing"
        }), 403

    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id", "")
    if not project_id:
        return jsonify({"error": api_error("project_id_required")}), 400

    project = Project.query.filter_by(
        id=project_id, user_id=user.id
    ).first_or_404()

    if not project.graph_built:
        return jsonify({"error": api_error("graph_not_built")}), 400

    # Validazione parametri contro limiti del piano
    plan = sub.plan
    num_agents = min(int(data.get("num_agents", 100)), plan.max_agents)
    num_rounds = min(int(data.get("num_rounds", 30)), plan.max_rounds)

    # Validazione provider LLM scelto
    provider = data.get("llm_provider", "groq")
    if not sub.provider_allowed(provider):
        return jsonify({
            "error": api_error("provider_not_in_plan", provider=provider),
            "allowed": plan.allowed_providers,
            "upgrade_url": "/pricing"
        }), 403

    # Nessuna chiave di sistema e nessuna credenziale: ogni chiamata LLM fallirebbe con HTTP 401
    from app.core.llm_router import user_has_llm_access
    if not user_has_llm_access(user.id):
        return jsonify({"error": api_error("no_llm_provider"), "code": "no_llm_provider"}), 400

    # Verifica che l'utente abbia la credenziale per il provider scelto (se non groq di sistema)
    credential_id = data.get("credential_id")
    if provider != "groq" or credential_id:
        from app.models import LLMCredential
        cred = LLMCredential.query.filter_by(
            user_id=user.id, provider=provider, is_active=True
        ).first()
        if not cred:
            return jsonify({
                "error": api_error("no_api_key", provider=provider)
            }), 400
        credential_id = cred.id
        # Heavy e' sempre ereditato dal progetto (coerenza grafo <-> report).
        # Payload puo' sovrascrivere SOLO agent e fast (A/B testing a livello simulazione).
        model_heavy = project.model_heavy or cred.model_heavy
        model_agent = data.get("model_agent") or cred.model_agent
        model_fast = data.get("model_fast") or cred.model_fast
    else:
        from app.config import Config
        cfg = Config()
        model_heavy = project.model_heavy or cfg.GROQ_MODEL_HEAVY
        model_agent = data.get("model_agent") or cfg.GROQ_MODEL_AGENT
        model_fast = data.get("model_fast") or cfg.GROQ_MODEL_FAST

    # Language of agents and report: the UI sends its locale; without it SIMULATION_DEFAULT_LANGUAGE (en)
    raw_language = data.get("language")
    if raw_language in (None, ""):
        language = configured_default_language(current_app.config.get("SIMULATION_DEFAULT_LANGUAGE"))
    else:
        language = normalize_language(raw_language)
    if language is None:
        return jsonify({
            "error": api_error("unsupported_language", language=raw_language,
                               allowed=", ".join(SUPPORTED_LANGUAGES)),
            "allowed": list(SUPPORTED_LANGUAGES),
        }), 400

    # Validazione template (opzionale)
    template_id = data.get("template_id") or None
    if template_id:
        from app.templates import get_registry as _get_tpl_registry
        if not _get_tpl_registry().get(template_id):
            return jsonify({"error": api_error("template_not_found", id=template_id)}), 400

    # Custom adversaries: lista di {name, role} dall'utente (opzionale)
    custom_adversaries = data.get("custom_adversaries") or None
    if custom_adversaries is not None:
        if not isinstance(custom_adversaries, list):
            return jsonify({"error": api_error("custom_adversaries_list")}), 400
        # Normalizza: tiene solo entries con name + role validi
        custom_adversaries = [
            {"name": str(x.get("name", "")).strip(), "role": str(x.get("role", "")).strip()}
            for x in custom_adversaries
            if isinstance(x, dict) and x.get("name") and x.get("role")
        ]
        if not custom_adversaries:
            custom_adversaries = None

    import uuid
    sim_id = str(uuid.uuid4())[:12]
    sim = Simulation(
        id=sim_id,
        project_id=project_id,
        user_id=user.id,
        name=data.get("name", t(language, "defaults.simulation_name", id=sim_id)),
        topic=data.get("topic", project.name),
        prediction_requirement=data.get("prediction_requirement", ""),
        platform_type=data.get("platform_type", "social_media"),
        language=language,
        llm_provider=provider,
        llm_credential_id=credential_id,
        model_heavy=model_heavy,
        model_agent=model_agent,
        model_fast=model_fast,
        num_agents=num_agents,
        num_rounds=num_rounds,
        template_id=template_id,
        custom_adversaries=custom_adversaries,
        status=SimulationStatus.PENDING,
    )
    # Contatore uso mensile: incremento atomico con il controllo del limite (vedi _reserve_quota)
    if not _reserve_quota(sub):
        db.session.rollback()
        return jsonify({
            "error": api_error("quota_exhausted"),
            "upgrade_url": "/pricing"
        }), 403
    db.session.add(sim)
    db.session.commit()

    AuditLog.log("simulation_created", user_id=user.id,
                 resource_type="simulation", resource_id=sim_id,
                 details={"provider": provider, "agents": num_agents, "language": language})

    return jsonify(sim.to_dict()), 201


@sim_bp.post("/<string:sim_id>/start")
@login_required
def start_simulation(sim_id: str):
    sim = Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    if sim.status not in (SimulationStatus.PENDING,):
        return jsonify({"error": api_error("already_in_state", status=sim.status.value)}), 400
    # Durante una ricostruzione il grafo non e' sul disco: lo spawn fallirebbe
    if not sim.project.graph_built:
        return jsonify({"error": api_error("graph_not_ready")}), 409

    sim.status = SimulationStatus.SPAWNING_AGENTS
    sim.started_at = datetime.now(timezone.utc)
    db.session.commit()

    # Avvia pipeline Celery: spawn_agents → run_simulation → report
    from celery import chain
    from app.simulation.tasks import spawn_agents_task, run_simulation_task, generate_report_task

    # Esegui i task in sequenza senza chain per evitare problemi con Celery 5
    from app.simulation.tasks import spawn_agents_task, run_simulation_task, generate_report_task
    # language as a keyword: the first positional argument stays the simulation id (lifecycle reads it)
    task = spawn_agents_task.apply_async(
        args=[sim_id, sim.project_id, sim.topic, sim.num_agents],
        kwargs={"language": sim.language},
        link=run_simulation_task.si(
            sim.id, sim.project_id, sim.topic,
            sim.prediction_requirement, sim.num_rounds, sim.platform_type,
            language=sim.language,
        ).set(link=generate_report_task.si(sim.id, sim.prediction_requirement, language=sim.language))
    )
    sim.celery_task_id = task.id
    db.session.commit()

    return jsonify({"ok": True, "task_id": task.id, "status": sim.status.value}), 202


def _chain_run_simulation(sim):
    """Legacy — non più usato."""
    pass


@sim_bp.get("/<string:sim_id>/status")
@login_required
def simulation_status(sim_id: str):
    sim = Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    result = sim.to_dict()

    # Arricchisci con dati task — legge dal file/DB, evita AsyncResult/DisabledBackend
    if sim.celery_task_id and sim.status in (
        SimulationStatus.SPAWNING_AGENTS,
        SimulationStatus.RUNNING,
        SimulationStatus.GENERATING_REPORT,
    ):
        result["task_state"] = sim.status.value if hasattr(sim.status, 'value') else str(sim.status)
        result["task_meta"] = {}

    # Metriche live da Redis se disponibili
    try:
        import redis, json
        from flask import current_app
        r = redis.from_url(current_app.config["REDIS_URL"], decode_responses=True)
        raw = r.get(f"sim:{sim_id}:latest_round")
        if raw:
            result["latest_round"] = json.loads(raw)
    except Exception:
        pass

    return jsonify(result), 200


@sim_bp.get("/<string:sim_id>/feed")
@login_required
def simulation_feed(sim_id: str):
    Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    store = _store()
    try:
        data = store.load_simulation(sim_id)
        feed = data.get("social_feed", [])
    except FileNotFoundError:
        feed = []

    # Paginazione manuale
    start = (page - 1) * per_page
    page_items = feed[start:start + per_page]

    return jsonify({
        "feed": page_items,
        "total": len(feed),
        "page": page,
        "per_page": per_page,
    }), 200


@sim_bp.post("/<string:sim_id>/stop")
@login_required
def stop_simulation(sim_id: str):
    sim = Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    from app.simulation import lifecycle

    # Prima si chiude la riga, solo se e' ancora aperta, poi si revoca il task: il task terminato e il
    # controllo delle simulazioni bloccate la trovano gia' chiusa. Prima la riga veniva scritta
    # STOPPED anche se era gia' FAILED, e restava con il messaggio dell'altro esito.
    closed = Simulation.query.filter(
        Simulation.id == sim.id,
        Simulation.status.notin_(
            (SimulationStatus.COMPLETED, SimulationStatus.FAILED, SimulationStatus.STOPPED)
        ),
    ).update(
        {"status": SimulationStatus.STOPPED, "error_message": lifecycle.STOPPED_BY_USER_MESSAGE,
         "error_detail": lifecycle.STOPPED_BY_USER_DETAIL},
        synchronize_session=False,
    )
    db.session.commit()
    db.session.refresh(sim)
    if not closed:
        return jsonify({"error": api_error("already_finished"), "simulation": sim.to_dict()}), 409

    if sim.celery_task_id:
        from celery.result import AsyncResult
        AsyncResult(sim.celery_task_id).revoke(terminate=True)
    lifecycle.schedule_memory_cleanup(sim.id)
    return jsonify({"ok": True, "simulation": sim.to_dict()}), 200


@sim_bp.get("/list")
@login_required
def list_simulations():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    pagination = Simulation.query.filter_by(user_id=g.current_user.id)\
        .order_by(Simulation.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "simulations": [s.to_dict() for s in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
    }), 200
