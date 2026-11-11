"""
/api/admin  — Area amministrativa (richiede ruolo admin o superadmin)

GET  /api/admin/stats              → dashboard KPI
GET  /api/admin/users              → lista utenti (paginata, filtri)
GET  /api/admin/users/<id>         → dettaglio utente
PUT  /api/admin/users/<id>         → modifica utente (ruolo, piano, stato)
POST /api/admin/users/<id>/suspend → sospendi account
POST /api/admin/users/<id>/activate→ riattiva account
DELETE /api/admin/users/<id>       → elimina account (soft)

GET  /api/admin/plans              → lista piani
POST /api/admin/plans              → crea piano
PUT  /api/admin/plans/<id>         → modifica piano

GET  /api/admin/simulations        → tutte le simulazioni
GET  /api/admin/audit              → log di audit

GET  /api/admin/users/<id>/impersonate → token temporaneo come utente (superadmin)
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, g

from app.core.i18n import api_error
from app.models import db, User, Plan, Subscription, Simulation, AuditLog
from app.models.user import Role
from app.models.plan import PlanTier, SubStatus
from .auth import admin_required, superadmin_required, _make_token

admin_bp = Blueprint("admin", __name__)


# ── Dashboard KPI ──────────────────────────────────────────────────────────────

@admin_bp.get("/stats")
@admin_required
def stats():
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    new_users_month = User.query.filter(User.created_at >= month_start).count()
    total_simulations = Simulation.query.count()
    running_simulations = Simulation.query.filter_by(status="running").count()
    sims_month = Simulation.query.filter(Simulation.created_at >= month_start).count()

    plans_dist = {}
    for sub in Subscription.query.filter_by(status=SubStatus.ACTIVE).all():
        tier = sub.plan.tier.value if sub.plan else "unknown"
        plans_dist[tier] = plans_dist.get(tier, 0) + 1

    return jsonify({
        "users": {
            "total": total_users,
            "active": active_users,
            "new_this_month": new_users_month,
        },
        "simulations": {
            "total": total_simulations,
            "running": running_simulations,
            "this_month": sims_month,
        },
        "plan_distribution": plans_dist,
    }), 200


# ── Gestione utenti ────────────────────────────────────────────────────────────

@admin_bp.get("/users")
@admin_required
def list_users():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    search = request.args.get("search", "")
    role_filter = request.args.get("role", "")
    plan_filter = request.args.get("plan", "")

    q = User.query
    if search:
        q = q.filter(
            db.or_(User.email.ilike(f"%{search}%"),
                   User.full_name.ilike(f"%{search}%"))
        )
    if role_filter:
        q = q.filter_by(role=role_filter)

    if plan_filter:
        q = q.join(Subscription).join(Plan).filter(Plan.tier == plan_filter)

    pagination = q.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "users": [u.to_dict() for u in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "page": page,
    }), 200


@admin_bp.get("/users/<string:user_id>")
@admin_required
def get_user(user_id: str):
    user = User.query.get_or_404(user_id)
    data = user.to_dict()
    data["simulations_count"] = Simulation.query.filter_by(user_id=user_id).count()
    data["credentials"] = [
        c.to_dict() for c in user.llm_credentials.filter_by(is_active=True).all()
    ]
    data["recent_audit"] = [
        l.to_dict() for l in
        AuditLog.query.filter_by(user_id=user_id)
        .order_by(AuditLog.created_at.desc()).limit(10).all()
    ]
    return jsonify(data), 200


@admin_bp.put("/users/<string:user_id>")
@admin_required
def update_user(user_id: str):
    user = User.query.get_or_404(user_id)
    # Un admin non modifica un superadmin (piano, nome, flag): come suspend e delete
    if user.is_superadmin and not g.current_user.is_superadmin:
        return jsonify({"error": api_error("cannot_modify_superadmin")}), 403
    data = request.get_json(silent=True) or {}

    # Solo superadmin può modificare ruoli
    if "role" in data:
        if not g.current_user.is_superadmin:
            return jsonify({"error": api_error("superadmin_only_roles")}), 403
        try:
            user.role = Role(data["role"])
        except ValueError:
            return jsonify({"error": api_error("invalid_role", role=data["role"])}), 400

    if "full_name" in data:
        user.full_name = data["full_name"]
    if "is_verified" in data:
        user.is_verified = bool(data["is_verified"])

    # Cambio piano
    if "plan_id" in data:
        plan = Plan.query.get(data["plan_id"])
        if not plan:
            return jsonify({"error": api_error("plan_not_found")}), 404
        if user.subscription:
            user.subscription.plan = plan
            user.subscription.status = SubStatus.ACTIVE
        else:
            sub = Subscription(user=user, plan=plan)
            db.session.add(sub)

    AuditLog.log("admin_user_updated", user_id=g.current_user.id,
                 resource_type="user", resource_id=user_id,
                 details=list(data.keys()))
    db.session.commit()
    return jsonify(user.to_dict()), 200


@admin_bp.post("/users/<string:user_id>/suspend")
@admin_required
def suspend_user(user_id: str):
    user = User.query.get_or_404(user_id)
    if user.is_superadmin:
        return jsonify({"error": api_error("cannot_suspend_superadmin")}), 403
    user.is_active = False
    AuditLog.log("admin_user_suspended", user_id=g.current_user.id,
                 resource_type="user", resource_id=user_id)
    db.session.commit()
    return jsonify({"ok": True}), 200


@admin_bp.post("/users/<string:user_id>/activate")
@admin_required
def activate_user(user_id: str):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    AuditLog.log("admin_user_activated", user_id=g.current_user.id,
                 resource_type="user", resource_id=user_id)
    db.session.commit()
    return jsonify({"ok": True}), 200


@admin_bp.post("/users/<string:user_id>/impersonate")
@superadmin_required
def impersonate(user_id: str):
    """Genera un token temporaneo (1h) per impersonare un utente."""
    user = User.query.get_or_404(user_id)
    token = _make_token(user.id, expires_hours=1)
    AuditLog.log("admin_impersonate", user_id=g.current_user.id,
                 resource_type="user", resource_id=user_id)
    db.session.commit()
    return jsonify({"token": token, "expires_in": 3600,
                    "impersonating": user.to_dict()}), 200


# ── Gestione piani ─────────────────────────────────────────────────────────────

@admin_bp.get("/plans")
@admin_required
def list_plans():
    plans = Plan.query.all()
    return jsonify([p.to_dict() for p in plans]), 200


@admin_bp.post("/plans")
@superadmin_required
def create_plan():
    data = request.get_json(silent=True) or {}
    required = ["name", "tier", "price_monthly"]
    for field in required:
        if field not in data:
            return jsonify({"error": api_error("required_field", field=field)}), 400

    plan = Plan(
        name=data["name"],
        tier=PlanTier(data["tier"]),
        price_monthly=float(data["price_monthly"]),
        price_yearly=float(data.get("price_yearly", data["price_monthly"] * 10)),
        max_simulations_per_month=int(data.get("max_simulations_per_month", 1)),
        max_agents=int(data.get("max_agents", 50)),
        max_rounds=int(data.get("max_rounds", 20)),
        max_projects=int(data.get("max_projects", 3)),
        max_file_size_mb=int(data.get("max_file_size_mb", 5)),
        allowed_providers=data.get("allowed_providers", ["groq"]),
        can_use_custom_api_keys=bool(data.get("can_use_custom_api_keys", False)),
        can_export_report=bool(data.get("can_export_report", False)),
        can_chat_with_agents=bool(data.get("can_chat_with_agents", False)),
        priority_queue=bool(data.get("priority_queue", False)),
    )
    db.session.add(plan)
    db.session.commit()
    return jsonify(plan.to_dict()), 201


@admin_bp.put("/plans/<string:plan_id>")
@superadmin_required
def update_plan(plan_id: str):
    plan = Plan.query.get_or_404(plan_id)
    data = request.get_json(silent=True) or {}
    fields = [
        "name", "price_monthly", "price_yearly",
        "max_simulations_per_month", "max_agents", "max_rounds",
        "max_projects", "max_file_size_mb", "allowed_providers",
        "can_use_custom_api_keys", "can_export_report",
        "can_chat_with_agents", "priority_queue", "is_active",
        "stripe_price_id_monthly", "stripe_price_id_yearly",
    ]
    for f in fields:
        if f in data:
            setattr(plan, f, data[f])
    db.session.commit()
    return jsonify(plan.to_dict()), 200


# ── Simulazioni ────────────────────────────────────────────────────────────────

@admin_bp.get("/simulations")
@admin_required
def list_simulations():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    status_filter = request.args.get("status", "")

    q = Simulation.query
    if status_filter:
        q = q.filter_by(status=status_filter)

    pagination = q.order_by(Simulation.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "simulations": [s.to_dict() for s in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
    }), 200


# ── Audit log ──────────────────────────────────────────────────────────────────

@admin_bp.get("/audit")
@admin_required
def audit_log():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    user_filter = request.args.get("user_id", "")
    action_filter = request.args.get("action", "")

    q = AuditLog.query
    if user_filter:
        q = q.filter_by(user_id=user_filter)
    if action_filter:
        q = q.filter(AuditLog.action.ilike(f"%{action_filter}%"))

    pagination = q.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "logs": [l.to_dict() for l in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
    }), 200


# ── Creazione utente da admin ──────────────────────────────────────────────────

@admin_bp.post("/users")
@admin_required
def create_user():
    """
    Crea un nuovo utente assegnando email, password, piano e ruolo.
    POST /api/admin/users
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "").strip()
    full_name = data.get("full_name", "").strip()
    plan_id = data.get("plan_id")
    role = data.get("role", "user")

    if not email or not password:
        return jsonify({"error": api_error("email_password_required")}), 400
    if len(password) < 8:
        return jsonify({"error": api_error("password_min_length")}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": api_error("email_taken")}), 409

    try:
        from app.models.user import Role
        user_role = Role(role)
    except ValueError:
        return jsonify({"error": api_error("invalid_role", role=role)}), 400

    # Solo superadmin può creare admin/superadmin
    if user_role in (Role.ADMIN, Role.SUPERADMIN) and not g.current_user.is_superadmin:
        return jsonify({"error": api_error("superadmin_only_create_admin")}), 403

    user = User(
        email=email,
        full_name=full_name,
        role=user_role,
        is_verified=True,
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)

    # Assegna piano
    if plan_id:
        plan = Plan.query.get(plan_id)
    else:
        plan = Plan.query.filter_by(tier="free").first()

    if plan:
        sub = Subscription(user=user, plan=plan)
        db.session.add(sub)

    AuditLog.log("admin_user_created", user_id=g.current_user.id,
                 resource_type="user",
                 details={"email": email, "role": role, "plan": plan.name if plan else None})
    db.session.commit()

    return jsonify(user.to_dict()), 201


@admin_bp.delete("/users/<string:user_id>")
@superadmin_required
def delete_user(user_id: str):
    """Elimina definitivamente un utente (solo superadmin)."""
    user = User.query.get_or_404(user_id)
    if user.id == g.current_user.id:
        return jsonify({"error": api_error("cannot_delete_self")}), 400
    if user.is_superadmin:
        return jsonify({"error": api_error("cannot_delete_superadmin")}), 400

    AuditLog.log("admin_user_deleted", user_id=g.current_user.id,
                 resource_type="user", resource_id=user_id,
                 details={"email": user.email})
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True}), 200
