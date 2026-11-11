"""
/api/templates — Template di simulazione

GET /api/templates/simulations        → lista template disponibili
GET /api/templates/simulations/<id>   → dettaglio completo di un template

Testi nella lingua della UI (Accept-Language); la simulazione usa poi la propria `language`.
"""
from flask import Blueprint, jsonify

from app.core.i18n import api_error, request_language
from app.templates import get_registry
from .auth import login_required

templates_bp = Blueprint("templates", __name__)


@templates_bp.get("/simulations")
@login_required
def list_simulation_templates():
    """Lista template di simulazione disponibili (schema leggero per UI)."""
    registry = get_registry()
    return jsonify(registry.list_all(request_language())), 200


@templates_bp.get("/simulations/<string:template_id>")
@login_required
def get_simulation_template(template_id: str):
    """Ritorna il template completo per id."""
    registry = get_registry()
    tpl = registry.get(template_id, request_language())
    if not tpl:
        return jsonify({"error": api_error("template_not_found", id=template_id)}), 404
    return jsonify(tpl), 200
