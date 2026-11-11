"""
Site settings API: landing page, branding, uploaded images.

GET  /api/site?lang=en|it            public: branding + landing content (no auth, ETag)
GET  /api/site/assets/<name>         public: an uploaded image (immutable, cached)
GET  /api/site/plans                 public, only with BILLING_ENABLED: active plans and the contact for a change
GET  /api/admin/site                 superadmin: full document, both languages, defaults
PUT  /api/admin/site                 superadmin: save the full document (validated, audited)
POST /api/admin/site/assets          superadmin: upload an image (multipart: file, kind)
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import structlog
from flask import Blueprint, current_app, g, jsonify, request, send_file

from app.core import site_settings as ss
from app.core.i18n import api_error, normalize_language, request_language
from app.models import AuditLog, Plan, SiteSettings, db
from app.models.site import SITE_SETTINGS_ID
from .auth import superadmin_required

site_bp = Blueprint("site", __name__)
log = structlog.get_logger()


# -- Helpers -------------------------------------------------------------------

def _uploads_dir() -> str:
    return current_app.config["UPLOADS_DIR"]


def _asset_exists(name: str) -> bool:
    path = ss.asset_path(_uploads_dir(), name)
    return bool(path) and os.path.isfile(path)


def _row():
    return db.session.get(SiteSettings, SITE_SETTINGS_ID)


def load_document() -> tuple[dict, int]:
    """(document, revision). No row: the defaults, revision 0."""
    row = _row()
    if row is None:
        return ss.default_document(), 0
    return ss.merge_stored(row.landing_enabled, row.branding, row.content), row.revision or 0


def product_name() -> str:
    """Product name for server-rendered text (PDF export). Defaults if the settings cannot be read."""
    try:
        return load_document()[0]["branding"]["product_name"]
    except Exception as e:  # never break an export over branding
        log.warning("site_settings_unreadable", error=str(e)[:200])
        return ss.default_branding()["product_name"]


def _client():
    return {"ip_address": request.remote_addr, "user_agent": (request.user_agent.string or "")[:512]}


# -- Public --------------------------------------------------------------------

@site_bp.get("/site")
def public_site():
    lang = normalize_language(request.args.get("lang")) or request_language()
    doc, _ = load_document()
    payload = ss.public_view(doc, lang)
    # BILLING_ENABLED (.env): the SPA shows plan and billing pages only when it is on
    payload["billing_enabled"] = bool(current_app.config.get("BILLING_ENABLED"))
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    etag = hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]

    if request.if_none_match.contains(etag):
        response = current_app.response_class(status=304)
    else:
        response = current_app.response_class(body, mimetype="application/json")
    response.set_etag(etag)
    # Cached, but revalidated on every use: a saved change shows on the next page load
    response.headers["Cache-Control"] = "public, no-cache"
    response.headers["Vary"] = "Accept-Language"
    return response


# Order of the plans on the plans page: the last one is the highest
PLAN_TIER_ORDER = {"free": 0, "pro": 1, "enterprise": 2}


def contact_email(lang: str) -> str:
    """The contact for a change of plan: the footer address set by the admin (Site & branding), else
    CONTACT_EMAIL. Empty if neither is set."""
    try:
        footer = load_document()[0]["content"][lang]["footer"]
        address = (footer.get("contact_email") or "").strip()
    except Exception as e:  # never break the plans page over the site settings
        log.warning("site_settings_unreadable", error=str(e)[:200])
        address = ""
    return address or (current_app.config.get("CONTACT_EMAIL") or "").strip()


@site_bp.get("/site/plans")
def public_plans():
    """The active plans, lowest first, each with its rank, and the contact for a change of plan.

    Only with BILLING_ENABLED. There is no payment flow: the admin changes plans, the page says whom to contact.
    The page used /api/admin/plans (admins only), so for every user it was empty.
    """
    if not current_app.config.get("BILLING_ENABLED"):
        return jsonify({"error": api_error("billing_disabled")}), 404
    lang = normalize_language(request.args.get("lang")) or request_language()
    plans = sorted(Plan.query.filter(Plan.is_active.isnot(False)).all(),
                   key=lambda p: (PLAN_TIER_ORDER.get(p.tier.value, len(PLAN_TIER_ORDER)), p.price_monthly))
    return jsonify({
        "plans": [{**p.to_dict(), "rank": rank} for rank, p in enumerate(plans)],
        "contact_email": contact_email(lang),
    }), 200


@site_bp.get("/site/assets/<string:name>")
def site_asset(name: str):
    path = ss.asset_path(_uploads_dir(), name)
    if not path or not os.path.isfile(path):
        return jsonify({"error": api_error("site_asset_not_found")}), 404
    ext = name.rsplit(".", 1)[1]
    response = send_file(path, mimetype=ss.ASSET_MIME[ext], conditional=True, etag=True,
                         max_age=31536000, download_name=name)
    # Content-addressed name: the bytes behind a URL never change
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["Content-Disposition"] = f'inline; filename="{name}"'
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


# -- Admin ---------------------------------------------------------------------

def _admin_payload(doc: dict, revision: int) -> dict:
    row = _row()
    return {
        "settings": ss.admin_view(doc),
        "revision": revision,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "defaults": ss.admin_view(ss.default_document()),
        "limits": ss.LIMITS,
        "item_limits": ss.ITEM_SECTIONS,
        "upload": {kind: {"max_bytes": r["max_bytes"], "min": r["min"], "max": r["max"]}
                   for kind, r in ss.IMAGE_RULES.items()},
    }


@site_bp.get("/admin/site")
@superadmin_required
def admin_get_site():
    doc, revision = load_document()
    return jsonify(_admin_payload(doc, revision)), 200


@site_bp.put("/admin/site")
@superadmin_required
def admin_update_site():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("settings"), dict):
        return jsonify({"error": api_error("site_invalid"), "fields": [{"path": "", "code": "invalid_type", "params": {}}]}), 400

    clean, errors = ss.validate_document(data["settings"], _asset_exists)
    if errors:
        return jsonify({"error": api_error("site_invalid"), "fields": errors}), 400

    old_doc, revision = load_document()
    if data.get("revision") != revision:
        return jsonify({"error": api_error("site_conflict"), "revision": revision}), 409

    row = _row()
    if row is None:
        row = SiteSettings(id=SITE_SETTINGS_ID, revision=0)
        db.session.add(row)
    row.landing_enabled = clean["landing_enabled"]
    row.branding = clean["branding"]
    row.content = clean["content"]
    row.revision = revision + 1
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = g.current_user.id

    changed = ss.changed_paths(old_doc, clean)
    AuditLog.log("admin_site_updated", user_id=g.current_user.id, resource_type="site_settings",
                 resource_id=str(SITE_SETTINGS_ID),
                 details={"revision": row.revision, "landing_enabled": clean["landing_enabled"], "changed": changed},
                 **_client())
    db.session.commit()

    removed = ss.prune_orphans(_uploads_dir(), ss.referenced_assets(clean))
    if removed:
        log.info("site_assets_pruned", removed=removed)
    return jsonify(_admin_payload(clean, row.revision)), 200


@site_bp.post("/admin/site/assets")
@superadmin_required
def admin_upload_asset():
    # Refused before reading the body: multipart overhead allowed on top of the file size
    if request.content_length and request.content_length > ss.MAX_UPLOAD_BYTES + 64 * 1024:
        return jsonify({"error": api_error("site_upload_too_large", max_mb=ss.MAX_UPLOAD_BYTES // (1024 * 1024)),
                        "code": "too_large"}), 413
    kind = request.form.get("kind", "")
    upload = request.files.get("file")
    if kind not in ss.ASSET_KINDS:
        return jsonify({"error": api_error("site_upload_invalid_kind"), "code": "invalid_kind"}), 400
    if upload is None:
        return jsonify({"error": api_error("site_upload_empty"), "code": "empty"}), 400

    data = upload.stream.read(ss.MAX_UPLOAD_BYTES + 1)
    try:
        out, ext, width, height = ss.process_image(data, kind, upload.filename or "")
    except ss.ImageRejected as e:
        status = 413 if e.code == "too_large" else 400
        return jsonify({"error": api_error(f"site_upload_{e.code}", **e.params), "code": e.code}), status

    name = ss.asset_name(kind, out, ext)
    ss.store_asset(_uploads_dir(), name, out)
    AuditLog.log("admin_site_asset_uploaded", user_id=g.current_user.id, resource_type="site_asset",
                 resource_id=name[:36],
                 details={"name": name, "kind": kind, "width": width, "height": height, "bytes": len(out),
                          "source_bytes": len(data)},
                 **_client())
    db.session.commit()
    return jsonify({"name": name, "url": ss.asset_url(name), "kind": kind,
                    "width": width, "height": height, "bytes": len(out)}), 201
