"""
/api/credentials  — CRUD chiavi LLM per utente

GET    /api/credentials              → lista credenziali utente corrente
POST   /api/credentials              → aggiungi credenziale
PUT    /api/credentials/<id>         → modifica (modelli preferiti, label)
DELETE /api/credentials/<id>         → elimina
POST   /api/credentials/<id>/verify  → testa la chiave con una chiamata ping
GET    /api/credentials/providers    → lista provider supportati + modelli disponibili
GET    /api/credentials/system-models → modelli usati senza una credenziale (Groq di sistema)
"""
import asyncio

from flask import Blueprint, current_app, request, jsonify, g

from app.models import db
from app.models.llm_credential import LLMCredential, SUPPORTED_PROVIDERS
from app.models.audit import AuditLog
from app.core.i18n import api_error, request_language
from app.core.llm_router import verify_credential
from .auth import login_required, plan_required

credentials_bp = Blueprint("credentials", __name__)


# ── Provider info (pubblico) ───────────────────────────────────────────────────

@credentials_bp.get("/providers")
def list_providers():
    """Restituisce i provider supportati con i modelli disponibili."""
    return jsonify(SUPPORTED_PROVIDERS), 200


@credentials_bp.get("/system-models")
@login_required
def system_models():
    cfg = current_app.config
    from app.core.llm_router import system_key_configured
    return jsonify({
        # False: no GROQ_API_KEY, every user needs a key of their own (AI connections)
        "available": system_key_configured(),
        "heavy": cfg["GROQ_MODEL_HEAVY"],
        "agent": cfg["GROQ_MODEL_AGENT"],
        "fast": cfg["GROQ_MODEL_FAST"],
    }), 200


# ── CRUD credenziali ───────────────────────────────────────────────────────────

@credentials_bp.get("")
@login_required
def list_credentials():
    creds = LLMCredential.query.filter_by(
        user_id=g.current_user.id, is_active=True
    ).all()
    return jsonify([c.to_dict() for c in creds]), 200


@credentials_bp.post("")
@login_required
@plan_required(feature="can_use_custom_api_keys")
def add_credential():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider", "").lower()
    api_key = data.get("api_key", "").strip()
    label = data.get("label", provider).strip()

    if provider not in SUPPORTED_PROVIDERS:
        return jsonify({"error": api_error("unsupported_provider", provider=provider)}), 400
    if not api_key:
        return jsonify({"error": api_error("api_key_required")}), 400

    # Controlla se esiste già per questo provider+label
    existing = LLMCredential.query.filter_by(
        user_id=g.current_user.id, provider=provider, label=label
    ).first()
    if existing:
        return jsonify({"error": api_error("credential_exists")}), 409

    # Verifica il piano consente il provider
    sub = g.current_user.subscription
    if sub and not sub.provider_allowed(provider):
        return jsonify({"error": api_error("plan_excludes_provider", provider=provider)}), 403

    meta = SUPPORTED_PROVIDERS[provider]
    models = meta.get("models", [])

    cred = LLMCredential(
        user_id=g.current_user.id,
        provider=provider,
        label=label,
        model_heavy=data.get("model_heavy", models[0] if models else None),
        model_agent=data.get("model_agent", models[0] if models else None),
        model_fast=data.get("model_fast", models[-1] if models else None),
    )
    cred.set_api_key(api_key)
    db.session.add(cred)

    AuditLog.log("credential_added", user_id=g.current_user.id,
                 resource_type="llm_credential", details={"provider": provider})
    db.session.commit()

    return jsonify(cred.to_dict()), 201


@credentials_bp.put("/<string:cred_id>")
@login_required
def update_credential(cred_id: str):
    cred = LLMCredential.query.filter_by(
        id=cred_id, user_id=g.current_user.id
    ).first_or_404()

    data = request.get_json(silent=True) or {}

    if "label" in data:
        cred.label = data["label"]
    if "model_heavy" in data:
        cred.model_heavy = data["model_heavy"]
    if "model_agent" in data:
        cred.model_agent = data["model_agent"]
    if "model_fast" in data:
        cred.model_fast = data["model_fast"]
    if "api_key" in data and data["api_key"].strip():
        cred.set_api_key(data["api_key"].strip())
        cred.is_verified = False  # richiede nuova verifica

    db.session.commit()
    return jsonify(cred.to_dict()), 200


@credentials_bp.delete("/<string:cred_id>")
@login_required
def delete_credential(cred_id: str):
    cred = LLMCredential.query.filter_by(
        id=cred_id, user_id=g.current_user.id
    ).first_or_404()

    cred.is_active = False  # soft delete
    AuditLog.log("credential_deleted", user_id=g.current_user.id,
                 resource_type="llm_credential", details={"provider": cred.provider})
    db.session.commit()
    return jsonify({"ok": True}), 200



@credentials_bp.get("/<string:cred_id>/models")
@login_required
def list_credential_models(cred_id: str):
    """Fetch modelli disponibili per una credenziale — live se possibile, statico come fallback."""
    cred = LLMCredential.query.filter_by(
        id=cred_id, user_id=g.current_user.id
    ).first_or_404()

    from app.models.llm_credential import SUPPORTED_PROVIDERS
    meta = SUPPORTED_PROVIDERS.get(cred.provider, {})
    static_models = meta.get("models", [])

    loop = asyncio.new_event_loop()
    try:
        models = loop.run_until_complete(_fetch_models_live(cred))
    except Exception:
        models = []
    finally:
        try:
            # Cancella task pendenti prima di chiudere (evita RuntimeError httpx)
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()

    return jsonify({
        "provider": cred.provider,
        "models": models or static_models,
        "live": bool(models),
    }), 200


async def _fetch_models_live(cred) -> list:
    """Fetcha modelli live da Groq o OpenRouter. Restituisce lista vuota su errore."""
    import httpx
    api_key = cred.get_api_key()

    try:
        if cred.provider == "groq":
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                r.raise_for_status()
                data = r.json()
                models = [
                    m["id"] for m in data.get("data", [])
                    if m.get("object") == "model"
                ]
                priority = ["llama-3.3-70b", "llama-3.1-70b", "llama-3.1-8b", "mixtral", "gemma"]
                def _rank(mid):
                    for i, p in enumerate(priority):
                        if p in mid:
                            return i
                    return 99
                return sorted(models, key=_rank)

        elif cred.provider == "openrouter":
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                r.raise_for_status()
                data = r.json()
                # Lista completa: un taglio per context_length escludeva interi vendor (anthropic/*)
                ids = [m["id"] for m in data.get("data", []) if m.get("id")]
                return sorted(
                    mid for mid in ids
                    if ":batch" not in mid and not mid.startswith(("~", "openrouter/"))
                )

    except Exception as e:
        return []

@credentials_bp.post("/<string:cred_id>/verify")
@login_required
def verify_credential_endpoint(cred_id: str):
    """Testa la chiave API con una chiamata di ping al provider."""
    cred = LLMCredential.query.filter_by(
        id=cred_id, user_id=g.current_user.id
    ).first_or_404()

    api_key = cred.get_api_key()
    meta = SUPPORTED_PROVIDERS.get(cred.provider, {})
    test_model = cred.model_fast or (meta.get("models") or [None])[0]

    loop = asyncio.new_event_loop()
    try:
        ok, message = loop.run_until_complete(
            verify_credential(cred.provider, api_key, test_model, request_language())
        )
    finally:
        loop.close()

    cred.is_verified = ok
    db.session.commit()

    return jsonify({"ok": ok, "message": message, "provider": cred.provider}), 200
