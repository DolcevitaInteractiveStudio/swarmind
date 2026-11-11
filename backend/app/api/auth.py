"""
Auth API + middleware JWT

POST /api/auth/register   → DISABILITATA (registrazione solo da admin)
POST /api/auth/login      → restituisce JWT
GET  /api/auth/me         → profilo utente corrente
PUT  /api/auth/me         → aggiorna profilo
"""
import functools
import secrets
from datetime import datetime, timezone, timedelta

import jwt
from flask import Blueprint, request, jsonify, g, current_app

from app.core import login_throttle as throttle
from app.core.i18n import api_error
from app.models import db, User, Plan, Subscription
from app.models.audit import AuditLog

auth_bp = Blueprint("auth", __name__)

# ── Helper JWT ─────────────────────────────────────────────────────────────────

def _make_token(user_id: str, expires_hours: int = 24) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config["SECRET_KEY"],
                      algorithms=["HS256"], options={"require": ["exp", "iat", "sub"]})


# ── Decoratori ────────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": api_error("token_missing")}), 401
        token = auth_header[7:]
        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": api_error("token_expired")}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": api_error("token_invalid")}), 401
        user = User.query.get(payload["sub"])
        if not user or not user.is_active:
            return jsonify({"error": api_error("user_not_found_or_disabled")}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @functools.wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not g.current_user.is_admin:
            return jsonify({"error": api_error("access_denied")}), 403
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    @functools.wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not g.current_user.is_superadmin:
            return jsonify({"error": api_error("access_denied")}), 403
        return f(*args, **kwargs)
    return decorated


def plan_required(feature: str = None, provider: str = None):
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            user = g.current_user
            sub = user.subscription
            if not sub or not sub.plan:
                return jsonify({"error": api_error("no_active_plan")}), 403
            if feature and not getattr(sub.plan, feature, False):
                return jsonify({
                    "error": api_error("feature_not_in_plan"),
                    "required_feature": feature,
                    "upgrade_url": "/pricing",
                }), 403
            if provider and not sub.provider_allowed(provider):
                return jsonify({
                    "error": api_error("provider_not_in_plan", provider=provider),
                    "upgrade_url": "/pricing",
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Endpoints ─────────────────────────────────────────────────────────────────

@auth_bp.post("/register")
def register():
    """Registrazione pubblica disabilitata — utenti creati solo dall'admin."""
    return jsonify({
        "error": api_error("registration_disabled")
    }), 403


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
        return jsonify({"error": api_error("email_password_required")}), 400
    email = email.strip().lower()
    # Per-IP and per-account limits on failed attempts (core/login_throttle.py)
    wait = throttle.blocked_for("login", request.remote_addr, email)
    if wait:
        return throttle.too_many_attempts(wait)
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        throttle.record_failure("login", request.remote_addr, email)
        return jsonify({"error": api_error("invalid_credentials")}), 401
    throttle.clear_account("login", email)
    if not user.is_active:
        return jsonify({"error": api_error("account_disabled")}), 403
    user.last_login = datetime.now(timezone.utc)
    AuditLog.log("user_login", user_id=user.id, ip_address=request.remote_addr)
    db.session.commit()
    token = _make_token(user.id)
    return jsonify({"token": token, "user": user.to_dict()}), 200


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(g.current_user.to_dict()), 200


@auth_bp.put("/me")
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    user = g.current_user
    if "full_name" in data:
        user.full_name = data["full_name"].strip()
    if "avatar_url" in data:
        user.avatar_url = data["avatar_url"]
    if "new_password" in data and data.get("current_password"):
        # The current password is checked like a login: same limits, counted apart
        wait = throttle.blocked_for("password", request.remote_addr, user.id)
        if wait:
            return throttle.too_many_attempts(wait)
        if not user.check_password(data["current_password"]):
            throttle.record_failure("password", request.remote_addr, user.id)
            return jsonify({"error": api_error("wrong_current_password")}), 400
        throttle.clear_account("password", user.id)
        if len(data["new_password"]) < 8:
            return jsonify({"error": api_error("new_password_min_length")}), 400
        user.set_password(data["new_password"])
    db.session.commit()
    return jsonify(user.to_dict()), 200
