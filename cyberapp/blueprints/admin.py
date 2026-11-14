"""Administrator module: user accounts and roles."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..forms import UserAdminForm
from ..models import Role, User
from ..security import role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/users")
@role_required(Role.ADMIN)
def users():
    role = request.args.get("role")
    query = User.query.order_by(User.created_at.desc())
    if role in Role.ALL:
        query = query.filter_by(role=role)
    return render_template("admin/users.html", users=query.all(), role_filter=role, roles=Role)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def edit_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    form = UserAdminForm(obj=user)
    form.role.choices = [(r, Role.LABELS[r]) for r in Role.ALL]
    if form.validate_on_submit():
        new_role, new_active = form.role.data, form.active.data
        removing_admin = user.is_admin and (new_role != Role.ADMIN or not new_active)
        active_admins = User.query.filter_by(role=Role.ADMIN, active=True).count()
        if user.id == current_user.id and removing_admin:
            flash("You cannot remove your own administrator access.", "danger")
        elif removing_admin and active_admins <= 1:
            flash("The system must keep at least one active administrator.", "danger")
        else:
            changes = []
            if user.role != new_role:
                changes.append(f"role {user.role} -> {new_role}")
            if user.active != new_active:
                changes.append("activated" if new_active else "deactivated")
            user.role, user.active = new_role, new_active
            db.session.commit()
            current_app.logger.info("Admin %s updated user %s: %s", current_user.username,
                                    user.username, ", ".join(changes) or "no changes")
            flash(f"User {user.username} updated.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/edit_user.html", form=form, user=user)
