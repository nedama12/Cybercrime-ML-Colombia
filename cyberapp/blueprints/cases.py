"""Case management: reporting suspicious URLs (create, read, update, delete)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import CaseForm, ResolveCaseForm
from ..ml.features import InvalidURL, domain_of, normalize_url
from ..ml.inference import LIMITATIONS, RECOMMENDATIONS, MissingFeatures, explain
from ..ml.inference import classify as run_classification
from ..ml.service import get_model_service
from ..models import ACTIONS, ACTIONS_BY_VERDICT, CHANNELS, CaseStatus, Role, UrlCase, utcnow
from ..security import role_required

bp = Blueprint("cases", __name__, url_prefix="/cases")

PER_PAGE = 15


def _get_case(case_id):
    case = db.session.get(UrlCase, case_id) or abort(404)
    if not case.can_view(current_user):
        abort(403)
    return case


def _form():
    form = CaseForm()
    form.channel.choices = CHANNELS
    return form


@bp.route("/")
@login_required
def index():
    query = UrlCase.query
    if not current_user.is_analyst:
        query = query.filter_by(reporter_id=current_user.id)  # reporters only see their own cases
    if request.args.get("mine") and current_user.is_analyst:
        query = query.filter_by(assignee_id=current_user.id)
    status = request.args.get("status")
    priority = request.args.get("priority")
    search = (request.args.get("q") or "").strip()
    if status in CaseStatus.LABELS:
        query = query.filter_by(status=status)
    if priority in ("high", "medium", "low", "pending"):
        query = query.filter_by(priority=priority)
    if search:
        query = query.filter(UrlCase.url.ilike(f"%{search}%"))
    pagination = query.order_by(UrlCase.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    filters = {"status": status or "", "priority": priority or "", "q": search,
               "mine": request.args.get("mine", "")}
    return render_template("cases/list.html", pagination=pagination, filters=filters,
                           statuses=CaseStatus.LABELS)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = _form()
    if form.validate_on_submit():
        try:
            url = normalize_url(form.url.data)
        except InvalidURL as exc:
            form.url.errors.append(str(exc))
        else:
            duplicate = UrlCase.query.filter(
                UrlCase.url == url, UrlCase.reporter_id == current_user.id,
                UrlCase.status.in_(CaseStatus.OPEN)).first()
            if duplicate:
                flash("You already have an open report for this URL.", "warning")
                return redirect(url_for("cases.detail", case_id=duplicate.id))
            case = UrlCase(url=url, domain=domain_of(url), channel=form.channel.data,
                           description=(form.description.data or "").strip() or None,
                           reporter_id=current_user.id)
            db.session.add(case)
            db.session.commit()
            current_app.logger.info("Case %s reported by %s (%s)", case.id, current_user.username, case.domain)
            flash("Thank you. Your report was registered.", "success")
            return redirect(url_for("cases.detail", case_id=case.id))
    return render_template("cases/form.html", form=form, case=None)


@bp.route("/<int:case_id>")
@login_required
def detail(case_id):
    case = _get_case(case_id)
    same_url = UrlCase.query.filter(UrlCase.url == case.url, UrlCase.id != case.id).count()
    latest = case.latest_prediction
    return render_template(
        "cases/detail.html", case=case, same_url=same_url, latest=latest,
        recommendation=RECOMMENDATIONS.get(latest.risk_level) if latest else None,
        limitations=LIMITATIONS, explanation=explain(latest) if latest else [],
        model_ready=get_model_service().ready)


@bp.route("/<int:case_id>/edit", methods=["GET", "POST"])
@login_required
def edit(case_id):
    case = _get_case(case_id)
    if not case.can_edit(current_user):
        abort(403)
    form = _form()
    if request.method == "GET":
        form.process(obj=case)
    if form.validate_on_submit():
        try:
            url = normalize_url(form.url.data)
        except InvalidURL as exc:
            form.url.errors.append(str(exc))
        else:
            if url != case.url and case.status != CaseStatus.NEW:
                form.url.errors.append("The URL cannot change after the case was classified.")
            else:
                case.url, case.domain = url, domain_of(url)
                case.channel = form.channel.data
                case.description = (form.description.data or "").strip() or None
                db.session.commit()
                flash("Case updated.", "success")
                return redirect(url_for("cases.detail", case_id=case.id))
    return render_template("cases/form.html", form=form, case=case)


@bp.route("/<int:case_id>/delete", methods=["POST"])
@login_required
def delete(case_id):
    case = _get_case(case_id)
    if not case.can_delete(current_user):
        abort(403)
    db.session.delete(case)
    db.session.commit()
    current_app.logger.info("Case %s deleted by %s", case_id, current_user.username)
    flash("Case deleted.", "info")
    return redirect(url_for("cases.index"))


@bp.route("/<int:case_id>/classify", methods=["POST"])
@role_required(Role.ANALYST, Role.ADMIN)
def classify(case_id):
    """Run the model on the case URL. If the model needs features that cannot be computed
    from the URL, ask the analyst for them and submit again."""
    case = _get_case(case_id)
    if not case.is_open:
        flash("Closed cases cannot be classified again. Reopen the case first.", "warning")
        return redirect(url_for("cases.detail", case_id=case.id))
    service = get_model_service()
    manual = {name: request.form.get(name) for name in service.features if name in request.form}
    try:
        prediction = run_classification(case.url, current_user, case=case, manual=manual)
    except MissingFeatures as exc:
        return render_template("cases/manual_features.html", case=case, missing=exc.missing)
    except (RuntimeError, ValueError) as exc:
        current_app.logger.error("Classification failed for case %s: %s", case.id, exc)
        flash(f"The case could not be classified: {exc}", "danger")
    else:
        flash(f"Classified as {prediction.label.upper()} ({prediction.probability:.0%} phishing "
              f"probability, {prediction.risk_level} risk).", "success")
    return redirect(url_for("cases.detail", case_id=case.id))


@bp.route("/<int:case_id>/review", methods=["POST"])
@role_required(Role.ANALYST, Role.ADMIN)
def start_review(case_id):
    """The analyst takes the case (classified -> under review) or reopens a closed one."""
    case = _get_case(case_id)
    try:
        case.move_to(CaseStatus.UNDER_REVIEW)
    except ValueError as exc:
        flash(str(exc), "warning")
    else:
        reopened = case.closed_at is not None
        case.assignee_id = current_user.id
        case.closed_at = None
        db.session.commit()
        current_app.logger.info("Case %s %s by %s", case.id, "reopened" if reopened else "taken",
                                current_user.username)
        flash("Case reopened." if reopened else "You are now reviewing this case.", "info")
    return redirect(url_for("cases.detail", case_id=case.id))


@bp.route("/<int:case_id>/resolve", methods=["GET", "POST"])
@role_required(Role.ANALYST, Role.ADMIN)
def resolve(case_id):
    """Record the actual outcome and the action taken, then close the case."""
    case = _get_case(case_id)
    if CaseStatus.CLOSED not in CaseStatus.TRANSITIONS.get(case.status, set()):
        flash("Only classified cases can be resolved. Classify the case with the model first.", "warning")
        return redirect(url_for("cases.detail", case_id=case.id))
    form = ResolveCaseForm(obj=case)
    form.action_taken.choices = list(ACTIONS.items())
    latest = case.latest_prediction
    if request.method == "GET" and latest and not case.actual_label:
        form.actual_label.data = latest.label  # start from the model's suggestion
    if form.validate_on_submit():
        verdict, action = form.actual_label.data, form.action_taken.data
        notes = (form.resolution_notes.data or "").strip()
        disagrees = latest is not None and latest.label != verdict
        if action not in ACTIONS_BY_VERDICT[verdict]:
            form.action_taken.errors.append(
                "This action is not coherent with the verdict: phishing must be blocked or "
                "escalated, legitimate URLs are dismissed.")
        elif disagrees and len(notes) < 10:
            form.resolution_notes.errors.append(
                "Explain why you disagree with the model (at least 10 characters). This feedback "
                "is used to evaluate and retrain the model.")
        else:
            case.move_to(CaseStatus.CLOSED)
            case.actual_label, case.action_taken = verdict, action
            case.resolution_notes = notes or None
            case.assignee_id = case.assignee_id or current_user.id
            case.closed_at = utcnow()
            db.session.commit()
            current_app.logger.info("Case %s closed by %s: verdict=%s action=%s model_agrees=%s",
                                    case.id, current_user.username, verdict, action, not disagrees)
            flash("Case closed. The verdict was recorded to monitor the model's real performance.", "success")
            return redirect(url_for("cases.detail", case_id=case.id))
    return render_template("cases/resolve.html", form=form, case=case, latest=latest)
