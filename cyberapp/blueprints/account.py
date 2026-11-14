"""Authenticated home (module launcher) and the user's own account."""
from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import ChangePasswordForm

bp = Blueprint("account", __name__)

# Module launcher: (endpoint, roles allowed or None for every authenticated user, card text).
MODULES = [
    ("cases.create", None, "Report", "+", "Report a suspicious URL",
     "Send a link you received by email, SMS or social media for review."),
    ("cases.index", None, "Case management", "⌕", "Cases",
     "Follow the status of the reported URLs."),
    ("admin.users", ("admin",), "Administration", "⚙", "Users and roles",
     "Activate accounts and assign the analyst or administrator role."),
    ("model.card", ("analyst", "admin"), "Machine Learning", "⌘", "Model card",
     "Version, features and evaluation results of the deployed model."),
    ("account.profile", None, "Account", "◎", "My account",
     "See your details and change your password."),
    ("docs.phase", None, "Documentation", "⌁", "CRISP-ML documentation",
     "Read how the data, the model and the system were built."),
]


@bp.route("/dashboard")
@login_required
def dashboard():
    modules = []
    for endpoint, roles, kicker, icon, title, text in MODULES:
        params = {"slug": "business-data-understanding"} if endpoint == "docs.phase" else {}
        modules.append({
            "url": url_for(endpoint, **params), "kicker": kicker, "icon": icon, "title": title,
            "text": text, "allowed": roles is None or current_user.has_role(*roles),
        })
    return render_template("account/dashboard.html", modules=modules)


@bp.route("/account", methods=["GET", "POST"])
@login_required
def profile():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current.data):
            form.current.errors.append("The current password is not correct.")
        else:
            current_user.set_password(form.password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("account.profile"))
    return render_template("account/profile.html", form=form)
