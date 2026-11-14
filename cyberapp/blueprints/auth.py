"""Registration, login and logout."""
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..forms import LoginForm, RegisterForm
from ..models import Role, User, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def _safe_next(target):
    """Only allow redirects to paths of this site (prevents open redirects)."""
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/"):
        return None
    return target


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("docs.home"))
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        if User.query.filter_by(username=username).first():
            form.username.errors.append("That username is already taken.")
        elif User.query.filter_by(email=email).first():
            form.email.errors.append("That email is already registered.")
        else:
            # The role is never read from the request: every new account is a reporter.
            # Only an administrator can promote a user (see the admin module).
            user = User(username=username, email=email, role=Role.REPORTER)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            current_app.logger.info("User registered: %s", username)
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("docs.home"))
    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier.lower())
        ).first()
        now = utcnow()
        locked_until = user.locked_until if user else None
        if locked_until and locked_until.tzinfo is None:  # SQLite returns naive datetimes
            locked_until = locked_until.replace(tzinfo=now.tzinfo)
        if locked_until and locked_until > now:
            flash("Too many failed attempts. Try again in a few minutes.", "danger")
        elif user and user.check_password(form.password.data):
            if not user.active:
                flash("This account is deactivated. Contact the administrator.", "danger")
            else:
                user.failed_logins = 0
                user.locked_until = None
                user.last_login_at = now
                db.session.commit()
                login_user(user, remember=form.remember.data)
                current_app.logger.info("Login: %s", user.username)
                flash(f"Welcome, {user.username}.", "success")
                return redirect(_safe_next(request.args.get("next")) or url_for("docs.home"))
        else:
            if user:
                user.failed_logins = (user.failed_logins or 0) + 1
                if user.failed_logins >= MAX_FAILED_LOGINS:
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    user.failed_logins = 0
                db.session.commit()
            current_app.logger.warning("Failed login for '%s'", identifier)
            # Same message for unknown user and wrong password (no account enumeration).
            flash("Invalid username or password.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "info")
    return redirect(url_for("docs.home"))
