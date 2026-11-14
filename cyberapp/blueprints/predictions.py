"""Quick URL check for analysts and the inference history."""
from datetime import datetime, time, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..forms import QuickCheckForm
from ..ml.features import InvalidURL, domain_of, normalize_url
from ..ml.inference import LIMITATIONS, RECOMMENDATIONS, MissingFeatures, classify, explain
from ..ml.service import get_model_service
from ..models import CHANNELS, CaseStatus, Prediction, Role, UrlCase, User
from ..security import role_required

bp = Blueprint("predictions", __name__, url_prefix="/predictions")

PER_PAGE = 25


@bp.route("/check", methods=["GET", "POST"])
@role_required(Role.ANALYST, Role.ADMIN)
def check():
    """Classify a URL received through another channel (phone call, ticket) before opening a case."""
    form = QuickCheckForm()
    prediction = None
    if form.validate_on_submit():
        try:
            prediction = classify(normalize_url(form.url.data), current_user)
        except InvalidURL as exc:
            form.url.errors.append(str(exc))
        except MissingFeatures as exc:
            flash("This model needs page features that cannot be computed from the URL. "
                  f"Open a case to enter them manually ({', '.join(exc.missing[:5])}...).", "warning")
        except (RuntimeError, ValueError) as exc:
            current_app.logger.error("Quick check failed: %s", exc)
            flash(f"The URL could not be classified: {exc}", "danger")
    return render_template(
        "predictions/check.html", form=form, prediction=prediction,
        recommendation=RECOMMENDATIONS.get(prediction.risk_level) if prediction else None,
        explanation=explain(prediction) if prediction else [], limitations=LIMITATIONS,
        model_ready=get_model_service().ready)


@bp.route("/<int:prediction_id>/open-case", methods=["POST"])
@role_required(Role.ANALYST, Role.ADMIN)
def open_case(prediction_id):
    """Turn a quick check into a case so it follows the normal review workflow."""
    prediction = db.session.get(Prediction, prediction_id) or abort(404)
    if prediction.case_id:
        return redirect(url_for("cases.detail", case_id=prediction.case_id))
    channel = request.form.get("channel", "other")
    case = UrlCase(url=prediction.url, domain=domain_of(prediction.url),
                   channel=channel if channel in dict(CHANNELS) else "other",
                   description="Opened by an analyst from a quick URL check.",
                   reporter_id=current_user.id, status=CaseStatus.CLASSIFIED,
                   priority=prediction.risk_level)
    db.session.add(case)
    prediction.case = case
    db.session.commit()
    flash(f"Case #{case.id} opened from the quick check.", "success")
    return redirect(url_for("cases.detail", case_id=case.id))


def _parse_date(value, end=False):
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return datetime.combine(day, time.max if end else time.min, tzinfo=timezone.utc)


@bp.route("/")
@role_required(Role.ANALYST, Role.ADMIN)
def history():
    args = request.args
    query = Prediction.query
    if args.get("risk") in ("high", "medium", "low"):
        query = query.filter_by(risk_level=args["risk"])
    if args.get("label") in ("phishing", "legitimate"):
        query = query.filter_by(label=args["label"])
    if args.get("version"):
        query = query.filter_by(model_version=args["version"])
    if args.get("user", type=int):
        query = query.filter_by(user_id=args.get("user", type=int))
    if start := _parse_date(args.get("start")):
        query = query.filter(Prediction.created_at >= start)
    if end := _parse_date(args.get("end"), end=True):
        query = query.filter(Prediction.created_at <= end)
    pagination = query.order_by(Prediction.created_at.desc()).paginate(
        page=args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    versions = [v for (v,) in db.session.query(Prediction.model_version).distinct().order_by(Prediction.model_version)]
    users = User.query.filter(User.role.in_((Role.ANALYST, Role.ADMIN))).order_by(User.username).all()
    filters = {k: args.get(k, "") for k in ("risk", "label", "version", "user", "start", "end")}
    return render_template("predictions/history.html", pagination=pagination, filters=filters,
                           versions=versions, users=users)
