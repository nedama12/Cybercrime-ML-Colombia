"""Monitoring dashboard for administrators (CRISP-ML phase 6)."""
from flask import Blueprint, render_template, request

from ..ml.inference import reference_stats
from ..ml.service import get_model_service
from ..models import Role
from ..monitoring import operational_review
from ..security import role_required

bp = Blueprint("monitoring", __name__, url_prefix="/monitoring")


@bp.route("/")
@role_required(Role.ADMIN)
def dashboard():
    days = request.args.get("days", 7, type=int)
    days = days if days in (1, 7, 30, 90) else 7
    include_simulated = request.args.get("real_only") != "1"
    review = operational_review(get_model_service(), reference_stats(), days=days,
                                include_simulated=include_simulated)
    return render_template("monitoring/dashboard.html", r=review)
