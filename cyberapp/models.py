"""Database models (SQLAlchemy). SQLite locally, PostgreSQL on Render."""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


class Role:
    """Roles and what each one is allowed to do (enforced on the server)."""
    REPORTER = "reporter"
    ANALYST = "analyst"
    ADMIN = "admin"
    ALL = (REPORTER, ANALYST, ADMIN)
    LABELS = {
        REPORTER: "Reporter",
        ANALYST: "Security analyst",
        ADMIN: "Administrator",
    }


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=Role.REPORTER)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True))

    def set_password(self, password):
        # Werkzeug uses scrypt with a random salt; only the hash is stored.
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # used by Flask-Login to block deactivated accounts
        return self.active

    def has_role(self, *roles):
        return self.role in roles

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_analyst(self):
        """Analysts and administrators can run the operational analyst functions."""
        return self.role in (Role.ANALYST, Role.ADMIN)

    @property
    def role_label(self):
        return Role.LABELS.get(self.role, self.role)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
