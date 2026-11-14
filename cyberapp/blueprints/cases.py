"""Case management: reporting suspicious URLs (create, read, update, delete)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import CaseForm
from ..ml.features import InvalidURL, domain_of, normalize_url
from ..models import CHANNELS, CaseStatus, UrlCase

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
    filters = {"status": status or "", "priority": priority or "", "q": search}
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
    return render_template("cases/detail.html", case=case, same_url=same_url)


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
