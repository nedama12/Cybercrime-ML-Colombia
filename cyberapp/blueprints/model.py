"""Model card for analysts and a health endpoint for the hosting platform."""
from flask import Blueprint, jsonify, render_template
from sqlalchemy import text

from ..extensions import db
from ..ml.service import get_model_service
from ..models import Role
from ..security import role_required

bp = Blueprint("model", __name__)


@bp.route("/model")
@role_required(Role.ANALYST, Role.ADMIN)
def card():
    service = get_model_service()
    return render_template("model/card.html", service=service, meta=service.metadata)


@bp.route("/healthz")
def health():
    """Used by Render's health check and by the monitoring review."""
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "error"
    status = get_model_service().status()
    ok = database == "ok"
    return jsonify({"status": "ok" if ok else "degraded", "database": database,
                    "model_ready": status["ready"], "model_version": status["model_version"]}), (200 if ok else 503)
