"""Incident reporting and user feedback (CRISP-ML phase 5 procedures)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import FeedbackForm, FeedbackResponseForm
from ..models import FEEDBACK_KINDS, FEEDBACK_STATUS, Feedback, Role, UrlCase, utcnow
from ..security import role_required

bp = Blueprint("feedback", __name__, url_prefix="/feedback")


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = FeedbackForm()
    form.kind.choices = list(FEEDBACK_KINDS.items())
    case = None
    case_id = request.args.get("case_id", type=int) or form.case_id.data
    if case_id:
        case = db.session.get(UrlCase, int(case_id))
        if case is None or not case.can_view(current_user):
            abort(404)
    if request.method == "GET":
        form.case_id.data = case.id if case else None
        if request.args.get("kind") in FEEDBACK_KINDS:
            form.kind.data = request.args["kind"]
    if form.validate_on_submit():
        item = Feedback(user_id=current_user.id, kind=form.kind.data, message=form.message.data.strip(),
                        case_id=case.id if case else None,
                        prediction_id=case.latest_prediction.id if case and case.latest_prediction else None)
        db.session.add(item)
        db.session.commit()
        level = current_app.logger.warning if item.kind == "incident" else current_app.logger.info
        level("Feedback %s (%s) from %s case=%s", item.id, item.kind, current_user.username, item.case_id)
        flash("Thank you. Your report was registered and will be reviewed by the administrator.", "success")
        return redirect(url_for("feedback.mine"))
    return render_template("feedback/form.html", form=form, case=case)


@bp.route("/")
@login_required
def mine():
    items = Feedback.query.filter_by(user_id=current_user.id).order_by(Feedback.created_at.desc()).all()
    return render_template("feedback/list.html", items=items, manage=False)


@bp.route("/manage")
@role_required(Role.ADMIN)
def manage():
    status = request.args.get("status")
    query = Feedback.query
    if status in FEEDBACK_STATUS:
        query = query.filter_by(status=status)
    items = query.order_by(Feedback.created_at.desc()).all()
    return render_template("feedback/list.html", items=items, manage=True, status_filter=status)


@bp.route("/<int:item_id>", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def respond(item_id):
    item = db.session.get(Feedback, item_id) or abort(404)
    form = FeedbackResponseForm(obj=item)
    form.status.choices = list(FEEDBACK_STATUS.items())
    if form.validate_on_submit():
        item.status = form.status.data
        item.admin_response = (form.admin_response.data or "").strip() or None
        item.resolved_at = utcnow() if item.status == "resolved" else None
        db.session.commit()
        flash("Feedback updated.", "success")
        return redirect(url_for("feedback.manage"))
    return render_template("feedback/respond.html", form=form, item=item)
