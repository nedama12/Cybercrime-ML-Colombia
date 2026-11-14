"""Database models (SQLAlchemy). SQLite locally, PostgreSQL on Render."""
import json
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
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))

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


class CaseStatus:
    """Workflow of a reported URL: new -> classified -> under_review -> closed."""
    NEW = "new"
    CLASSIFIED = "classified"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"
    LABELS = {NEW: "New", CLASSIFIED: "Classified", UNDER_REVIEW: "Under review", CLOSED: "Closed"}
    OPEN = (NEW, CLASSIFIED, UNDER_REVIEW)
    # Allowed transitions (business rule enforced in UrlCase.move_to).
    TRANSITIONS = {
        NEW: {CLASSIFIED},
        CLASSIFIED: {UNDER_REVIEW, CLOSED},
        UNDER_REVIEW: {CLOSED},
        CLOSED: {UNDER_REVIEW},  # reopen
    }


ACTIONS = {
    "blocked": "URL blocked and affected users warned",
    "escalated": "Escalated to the security team or the authorities",
    "dismissed": "Dismissed: no action needed",
}
# Which final actions are coherent with each verdict.
ACTIONS_BY_VERDICT = {"phishing": ("blocked", "escalated"), "legitimate": ("dismissed",)}


CHANNELS = [
    ("email", "Email"),
    ("sms", "SMS / text message"),
    ("messaging", "Messaging app (WhatsApp, Telegram)"),
    ("social_media", "Social media"),
    ("website", "Website or search result"),
    ("other", "Other"),
]


class UrlCase(db.Model):
    """A suspicious URL reported by a user: the central business entity."""
    __tablename__ = "url_cases"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2048), nullable=False)
    domain = db.Column(db.String(255), nullable=False, index=True)
    channel = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default=CaseStatus.NEW, index=True)
    priority = db.Column(db.String(10), nullable=False, default="pending", index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    actual_label = db.Column(db.String(20))      # analyst verdict: phishing / legitimate
    action_taken = db.Column(db.String(20))
    resolution_notes = db.Column(db.Text)
    closed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)

    reporter = db.relationship("User", foreign_keys=[reporter_id], backref="reported_cases")
    assignee = db.relationship("User", foreign_keys=[assignee_id])

    def move_to(self, status):
        if status not in CaseStatus.TRANSITIONS.get(self.status, set()):
            raise ValueError(f"A {self.status_label.lower()} case cannot move to "
                             f"{CaseStatus.LABELS[status].lower()}.")
        self.status = status

    @property
    def action_label(self):
        return ACTIONS.get(self.action_taken, "-")

    @property
    def model_agrees(self):
        """Did the model's latest prediction match the analyst's verdict? None if unknown."""
        if not self.actual_label or not self.latest_prediction:
            return None
        return self.latest_prediction.label == self.actual_label

    @property
    def latest_prediction(self):
        return self.predictions[0] if self.predictions else None

    @property
    def status_label(self):
        return CaseStatus.LABELS.get(self.status, self.status)

    @property
    def channel_label(self):
        return dict(CHANNELS).get(self.channel, self.channel)

    @property
    def is_open(self):
        return self.status in CaseStatus.OPEN

    def can_view(self, user):
        return user.is_analyst or user.id == self.reporter_id

    def can_edit(self, user):
        # Reporters may correct their report only until it has been classified.
        if user.is_analyst:
            return self.is_open
        return user.id == self.reporter_id and self.status == CaseStatus.NEW

    def can_delete(self, user):
        # Classified cases are kept for traceability; only administrators may remove them.
        return user.is_admin or (user.id == self.reporter_id and self.status == CaseStatus.NEW)


class Prediction(db.Model):
    """Inference history: every model output with date, user, result and model version."""
    __tablename__ = "predictions"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("url_cases.id", ondelete="SET NULL"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    url = db.Column(db.String(2048), nullable=False)
    probability = db.Column(db.Float, nullable=False)
    label = db.Column(db.String(20), nullable=False)
    risk_level = db.Column(db.String(10), nullable=False, index=True)
    threshold = db.Column(db.Float, nullable=False)
    model_name = db.Column(db.String(80), nullable=False)
    model_version = db.Column(db.String(40), nullable=False, index=True)
    features_json = db.Column(db.Text, nullable=False)
    sources_json = db.Column(db.Text)
    latency_ms = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)

    case = db.relationship("UrlCase", backref=db.backref(
        "predictions", order_by="Prediction.created_at.desc()", passive_deletes=True))
    user = db.relationship("User")

    @property
    def features(self):
        return json.loads(self.features_json or "{}")

    @property
    def sources(self):
        return json.loads(self.sources_json or "{}")

    @property
    def used_manual_inputs(self):
        return "manual" in self.sources.values()
