"""Cybercrime Colombia: web information system for citizen cybercrime reports.

Citizens register, report a cybercrime incident in about 90 seconds, receive the
category identified by the report classifier and clear next steps. Analysts
review every report, confirm or correct the category and close the case; the
confirmed reports become new training data. Administrators manage accounts,
roles, model versions and the operational monitoring of the platform.

Roles: citizen (default on registration), analyst and admin. Roles are only
granted by an administrator, by the ANALYST_EMAILS / ADMIN_EMAILS settings or
by the `flask set-role` command, never by the browser.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sqlite3
import csv
import io
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlsplit

import click
import pandas as pd
from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from sklearn import __version__ as sklearn_version
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from src import operations
from src.report_features import AFFECTED, CHANNELS
from src.report_model import (CATEGORY_INFO, category_info, classify_report, load_model, model_available,
                              model_info as report_model_info)
from src.territorial_analysis import build_analysis_context

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data/processed/crimes_processed.csv"
DEPT_SUMMARY_PATH = ROOT / "data/processed/summary_department_category.csv"
REPORTS_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"
METRICS_PATH = REPORTS_DIR / "model_comparison.csv"
INFO_PATH = MODELS_DIR / "best_model_info.json"
CLASS_REPORT_DIR = REPORTS_DIR / "classification_reports"
CONFUSION_DIR = REPORTS_DIR / "confusion_matrices"
REPORT_MODEL_DIR = REPORTS_DIR / "report_classifier"
INSTANCE_DIR = ROOT / "instance"
USER_DB_PATH = Path(os.environ.get("USER_DB_PATH", str(INSTANCE_DIR / "cybercrime.sqlite3")))
SECRET_KEY_PATH = INSTANCE_DIR / "flask_secret_key"
ANALYST_EMAILS = {e.strip().lower() for e in os.environ.get("ANALYST_EMAILS", "").split(",") if e.strip()}
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
ROLES = {"citizen": "Citizen", "analyst": "Analyst", "admin": "Administrator"}
STAFF_ROLES = {"analyst", "admin"}
PRIORITIES = {"high": "High", "medium": "Medium", "normal": "Normal"}
TICKET_KINDS = {"wrong_result": "The classification looks wrong", "technical_issue": "Technical problem or error",
                "data_request": "Personal data request (access, correction, deletion)",
                "suggestion": "Suggestion"}
TICKET_STATUSES = {"open": "Open", "in_progress": "In progress", "resolved": "Resolved"}
EVENT_LABELS = {"created": "Report received and classified", "edited": "Report edited by the citizen",
                "reclassified": "Classified again after the edit", "feedback": "Citizen answered the result check",
                "status": "Status changed", "category": "Category confirmed by an analyst",
                "note": "Analyst note updated", "deleted": "Report deleted"}
# Login protection is stored in the database, so it works the same with several
# gunicorn workers: 5 failures for one email from one IP within 10 minutes lock
# that pair for 2 minutes; 20 failures from one IP (any email) lock the IP.
LOGIN_ATTEMPT_WINDOW_SECONDS = 10 * 60
LOGIN_LOCK_SECONDS = 2 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_MAX_FAILURES_PER_IP = 20
PASSWORD_HASH_METHOD = "scrypt"
PASSWORD_MIN, PASSWORD_MAX = 8, 128
COMMON_PASSWORDS = {"password", "password1", "password123", "12345678", "123456789", "1234567890",
                    "qwerty123", "qwertyuiop", "11111111", "abc12345", "colombia123", "contrasena1",
                    "iloveyou1", "admin1234", "welcome1", "letmein1"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
STATUSES = {"received": "Received", "in_review": "In review", "closed": "Closed"}
MODELS = [("decision_tree", "Decision Tree"), ("random_forest", "Random Forest"),
          ("logistic_regression", "Logistic Regression")]
# Checked when the email does not exist, so a wrong email takes as long as a wrong password.
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(16), method=PASSWORD_HASH_METHOD)
logger = logging.getLogger(__name__)


def load_secret_key() -> str:
    configured = os.environ.get("FLASK_SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("FLASK_SECRET_KEY must be at least 32 characters long.")
        return configured
    if os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("FLASK_SECRET_KEY is required in production.")
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_KEY_PATH.exists():
        SECRET_KEY_PATH.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return SECRET_KEY_PATH.read_text(encoding="utf-8").strip()


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                  SESSION_REFRESH_EACH_REQUEST=True)
if model_available():
    load_model()  # load once at start-up so the first report is not slowed down
if os.environ.get("BEHIND_PROXY") == "1":
    # Render sits behind a proxy: trust one hop so request.remote_addr is the real client IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
# Endpoints that serve files: they are not written to the request log.
UNLOGGED_ENDPOINTS = {"static", "report_figure", "report_file", "confusion_image", "report_confusion_image",
                      "comparison_image", "healthz"}


# --------------------------------------------------------------------------- database
@contextmanager
def connect_db():
    USER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(USER_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


_READY_DATABASES: set[str] = set()

# Existing project accounts that must have administrator access.
# This list is applied only to accounts already present in the database.
PROJECT_ADMIN_EMAILS = (
    "neiderfelipe2003@gmail.com",
    "astrithdrincon@ucundinamarca.edu.co",
    "nicolasuchuvo123@gmail.com",
)


def promote_project_admins() -> None:
    """Promote the specified existing accounts once during database initialization."""
    with connect_db() as connection:
        for email in PROJECT_ADMIN_EMAILS:
            changed = connection.execute(
                "UPDATE users SET role = 'admin', session_version = session_version + 1 "
                "WHERE email = ? COLLATE NOCASE AND role != 'admin'",
                (email,),
            ).rowcount
            if changed:
                logger.info("Project administrator role granted to existing account: %s", email)


def ensure_database() -> None:
    """Create or migrate the schema once per process and database file."""
    key = str(USER_DB_PATH)
    if key in _READY_DATABASES and USER_DB_PATH.exists():
        return
    create_schema()
    promote_project_admins()
    _READY_DATABASES.add(key)


def create_schema() -> None:
    with connect_db() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'citizen',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "name" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "role" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'citizen'")
        if "session_version" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1")
        if "last_login_at" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
        connection.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            ip TEXT NOT NULL,
            attempted_at REAL NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup "
                           "ON login_attempts(ip, email, attempted_at)")
        connection.execute("""CREATE TABLE IF NOT EXISTS incident_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            occurred_on TEXT NOT NULL,
            department TEXT NOT NULL,
            municipality TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL,
            affected TEXT NOT NULL,
            amount_lost INTEGER,
            description TEXT NOT NULL,
            predicted_category TEXT NOT NULL,
            confidence REAL NOT NULL,
            alternatives_json TEXT NOT NULL DEFAULT '[]',
            needs_review INTEGER NOT NULL DEFAULT 0,
            model_version TEXT NOT NULL DEFAULT '',
            inference_ms REAL,
            duration_seconds INTEGER,
            user_agrees INTEGER,
            status TEXT NOT NULL DEFAULT 'received',
            confirmed_category TEXT,
            analyst_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_reports_user_created "
                           "ON incident_reports(user_id, created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_reports_status "
                           "ON incident_reports(status)")
        if "active" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        report_columns = {row["name"] for row in connection.execute("PRAGMA table_info(incident_reports)")}
        for name, ddl in (("priority", "TEXT NOT NULL DEFAULT 'normal'"), ("closed_at", "TEXT"),
                          ("reviewed_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL")):
            if name not in report_columns:
                connection.execute(f"ALTER TABLE incident_reports ADD COLUMN {name} {ddl}")
        # Audit trail of every change to a report (who, what, when).
        connection.execute("""CREATE TABLE IF NOT EXISTS report_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL REFERENCES incident_reports(id) ON DELETE CASCADE,
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_report ON report_events(report_id, id)")
        # Inference history: date, user, result and model version of every prediction.
        connection.execute("""CREATE TABLE IF NOT EXISTS inferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            report_id INTEGER REFERENCES incident_reports(id) ON DELETE SET NULL,
            source TEXT NOT NULL,
            model_version TEXT NOT NULL,
            predicted_category TEXT NOT NULL,
            confidence REAL NOT NULL,
            needs_review INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            input_chars INTEGER NOT NULL DEFAULT 0,
            inference_ms REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_inferences_created ON inferences(created_at)")
        # Feedback and incident notifications from users, handled by staff.
        connection.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            report_id INTEGER REFERENCES incident_reports(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            staff_response TEXT NOT NULL DEFAULT '',
            handled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT
        )""")
        # Operational log: every page or form request with its status and response time.
        connection.execute("""CREATE TABLE IF NOT EXISTS request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            method TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            status INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            user_id INTEGER,
            error TEXT NOT NULL DEFAULT ''
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_request_log_created ON request_log(created_at)")
        # Model registry: one row per released model version.
        connection.execute("""CREATE TABLE IF NOT EXISTS model_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            version TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            artifact TEXT NOT NULL,
            sklearn_version TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            trained_at TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 0,
            registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(model_name, version)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS operational_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            period_days INTEGER NOT NULL,
            metrics_json TEXT NOT NULL,
            findings TEXT NOT NULL,
            actions TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        # Administrative actions on accounts (role changes, deactivation).
        connection.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        register_active_model(connection)


def register_active_model(connection) -> None:
    """Record the deployed classifier in the model registry and mark it as the active version."""
    info = report_model_info()
    if not info:
        return
    version = f"{info.get('algorithm', 'unknown')}@{info.get('version', '-')}"
    connection.execute(
        """INSERT OR IGNORE INTO model_versions (model_name, version, algorithm, artifact, sklearn_version,
           metrics_json, trained_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (info.get("name", "Incident report classifier"), version, info.get("algorithm", ""),
         "models/report_classifier.joblib", str(info.get("sklearn_version", sklearn_version)),
         json.dumps(info.get("metrics", {})), str(info.get("training_date_utc", info.get("version", "")))))
    connection.execute("UPDATE model_versions SET active = CASE WHEN version = ? THEN 1 ELSE 0 END", (version,))


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    logger.exception("SQLite database error", exc_info=error)
    g.error_name = type(error).__name__
    return render_template("error.html", page_title="Service unavailable",
                           message="We could not complete the operation. Please try again later."), 503


@app.errorhandler(500)
def server_error(error):
    original = getattr(error, "original_exception", None) or error
    logger.error("Unhandled error on %s", request.path, exc_info=original)
    g.error_name = type(original).__name__
    return render_template("error.html", page_title="Unexpected error",
                           message="Something failed on our side. The team has been notified in the "
                                   "error log; please try again later."), 500


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", page_title="Access denied",
                           message="Your role does not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", page_title="Page not found",
                           message="The page you are looking for does not exist."), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", page_title="Invalid request",
                           message=getattr(error, "description", "Invalid request.")), 400


@app.before_request
def prepare_request():
    g.started = time.perf_counter()
    ensure_database()
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        with connect_db() as connection:
            user = connection.execute(
                "SELECT id, name, email, role, session_version, active FROM users WHERE id = ?",
                (user_id,)).fetchone()
        # A password change bumps session_version and signs out every other session;
        # a deactivated account loses access on its next request.
        if user is None or not user["active"] or session.get("session_version") != user["session_version"]:
            session.clear()
        else:
            g.user = user


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if g.get("user") is not None or request.endpoint in {"login", "register"}:
        # Private pages and login forms must not be stored by the browser or proxies.
        response.headers["Cache-Control"] = "no-store"
    log_request(response.status_code)
    return response


def log_request(status: int) -> None:
    """Store method, endpoint, status and response time (no query strings or form data)."""
    if request.endpoint in UNLOGGED_ENDPOINTS or "started" not in g:
        return
    duration = (time.perf_counter() - g.started) * 1000
    user = g.get("user")
    try:
        with connect_db() as connection:
            connection.execute(
                "INSERT INTO request_log (method, endpoint, status, duration_ms, user_id, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (request.method, request.endpoint or "not_found", status, duration,
                 user["id"] if user else None, g.get("error_name", "")))
    except sqlite3.Error:
        logger.exception("Could not write the request log")
    if status >= 500:
        logger.error("request failed endpoint=%s status=%s ms=%.0f", request.endpoint, status, duration)


# --------------------------------------------------------------------------- security helpers
def client_ip() -> str:
    return request.remote_addr or "unknown"


def login_retry_after(email: str) -> int:
    """Seconds the user must wait before trying again (0 = allowed)."""
    now = time.time()
    since = now - LOGIN_ATTEMPT_WINDOW_SECONDS
    with connect_db() as connection:
        connection.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (since,))
        pair = connection.execute(
            "SELECT COUNT(*), MAX(attempted_at) FROM login_attempts "
            "WHERE ip = ? AND email = ? AND attempted_at >= ?", (client_ip(), email, since)).fetchone()
        per_ip = connection.execute(
            "SELECT COUNT(*), MAX(attempted_at) FROM login_attempts WHERE ip = ? AND attempted_at >= ?",
            (client_ip(), since)).fetchone()
    waits = [0]
    for (count, last), limit in ((pair, LOGIN_MAX_FAILURES), (per_ip, LOGIN_MAX_FAILURES_PER_IP)):
        if count >= limit and last:
            waits.append(int(last + LOGIN_LOCK_SECONDS - now + 0.999))
    return max(0, max(waits))


def record_login_failure(email: str) -> None:
    with connect_db() as connection:
        connection.execute("INSERT INTO login_attempts (email, ip, attempted_at) VALUES (?, ?, ?)",
                           (email, client_ip(), time.time()))


def clear_login_failures(email: str) -> None:
    with connect_db() as connection:
        connection.execute("DELETE FROM login_attempts WHERE email = ? AND ip = ?", (email, client_ip()))


def password_problem(password: str, email: str = "", name: str = "") -> str | None:
    """Return a message if the password is not acceptable, otherwise None."""
    if len(password) < PASSWORD_MIN:
        return f"The password must have at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"The password can have at most {PASSWORD_MAX} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "The password must include at least one letter and one number."
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        return "That password is too common. Choose a different one."
    personal = [email.split("@", 1)[0].lower().replace(".", ""), name.lower().replace(" ", "")]
    personal += name.lower().split()
    if any(len(part) >= 4 and part in lowered for part in personal):
        return "The password must not contain your email or name."
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=PASSWORD_HASH_METHOD)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if not request.path.startswith("/report"):  # the login page explains the report case
                flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles: str):
    """Server-side authorization: the signed-in user must have one of `roles` (403 otherwise)."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                logger.warning("access denied user_id=%s role=%s endpoint=%s",
                               g.user["id"], g.user["role"], request.endpoint)
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


# TEMPORARY: role restrictions disabled for the project demonstration.
# Login is still required; restore role_required before public production use.
staff_required = login_required
admin_required = login_required


def initial_role(email: str) -> str:
    """Role given at registration: always citizen unless the server configuration says otherwise."""
    if email in ADMIN_EMAILS:
        return "admin"
    if email in ANALYST_EMAILS:
        return "analyst"
    return "citizen"


def validate_csrf() -> None:
    expected = session.get("_csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="This form expired or its security token is invalid. Reload the page.")


def safe_next(default: str) -> str:
    """Only allow redirects to paths of this site (blocks //evil.com, /\\evil.com, http://...)."""
    destination = request.args.get("next", "").strip()
    parts = urlsplit(destination)
    if (destination.startswith("/") and not destination.startswith(("//", "/\\"))
            and not parts.scheme and not parts.netloc and "\\" not in destination):
        return destination
    return default


def start_session(user: sqlite3.Row) -> None:
    """Start a fresh session (prevents session fixation) and remember the login time."""
    session.clear()
    session["user_id"] = user["id"]
    session["session_version"] = user["session_version"]
    session.permanent = True
    with connect_db() as connection:
        connection.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))


# --------------------------------------------------------------------------- data helpers
@lru_cache(maxsize=1)
def get_dataset() -> pd.DataFrame:
    if not DATA_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(DATA_PATH)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def get_info() -> dict:
    return read_json(INFO_PATH, {}) or {}


def get_metrics() -> list[dict]:
    if not METRICS_PATH.exists():
        return []
    return pd.read_csv(METRICS_PATH).fillna(0).to_dict(orient="records")


def get_report_metrics() -> list[dict]:
    path = REPORT_MODEL_DIR / "model_comparison.csv"
    if not path.exists():
        return []
    return pd.read_csv(path).fillna(0).to_dict(orient="records")


def get_model_summaries() -> list[dict]:
    best = get_info().get("algorithm")
    metrics = get_metrics()
    report_metrics = get_report_metrics()
    report_best = report_model_info().get("algorithm")
    summaries = []
    for key, title in MODELS:
        summaries.append({
            "key": key, "title": title,
            "benchmark": next((row for row in metrics if row.get("model") == key), {}),
            "benchmark_best": key == best,
            "report": next((row for row in report_metrics if row.get("model") == key), {}),
            "report_best": key == report_best,
            "benchmark_classes": read_json(CLASS_REPORT_DIR / f"{key}.json", {}) or {},
            "report_classes": (read_json(REPORT_MODEL_DIR / "classification_reports" / f"{key}.json", {})
                               or {}).get("holdout", {}),
        })
    return summaries


def pretty_department(value: str) -> str:
    special = {"BOGOTA D C": "Bogota D.C.",
               "ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA": "San Andres and Providencia"}
    return special.get(value, value.title().replace(" De ", " de ").replace(" Del ", " del "))


@lru_cache(maxsize=1)
def departments() -> list[tuple[str, str]]:
    df = get_dataset()
    if df.empty:
        return []
    return sorted(((value, pretty_department(value)) for value in df["department_norm"].dropna().unique()),
                  key=lambda pair: pair[1])


@lru_cache(maxsize=1)
def department_counts() -> dict[tuple[str, str], int]:
    df = get_dataset()
    if df.empty:
        return {}
    grouped = df.groupby(["department_norm", "category"])["total_cases"].sum()
    return {key: int(value) for key, value in grouped.items()}


def dataset_context() -> dict:
    df = get_dataset()
    if df.empty:
        return {"available": False, "rows": 0, "columns": [], "distribution": [], "sample": []}
    distribution = [{"category": str(k), "label": category_info(str(k))["label"]
                     if k in CATEGORY_INFO else str(k).replace("_", " ").title(), "count": int(v)}
                    for k, v in df["category"].value_counts().items()]
    columns = [{"name": col, "dtype": str(df[col].dtype), "missing": int(df[col].isna().sum()),
                "unique": int(df[col].nunique(dropna=True))} for col in df.columns]
    complete = df[(df["partial_year"] == 0) & (df["report_year"] < 2026)]  # 2026 is still in progress
    by_year = complete.groupby("report_year")["total_cases"].sum()
    return {"available": True, "rows": len(df), "column_count": len(df.columns),
            "columns": columns, "distribution": distribution,
            "sample": df.head(8).fillna("").astype(str).to_dict(orient="records"),
            "missing_total": int(df.isna().sum().sum()), "duplicates": int(df.duplicated().sum()),
            "total_cases": int(df["total_cases"].sum()),
            "years": f"{int(df['report_year'].min())}-{int(df['report_year'].max())}",
            "by_year": [{"year": int(y), "cases": int(c)} for y, c in by_year.items()]}


def reference_number(report_id: int, created_at: str) -> str:
    return f"CC-{created_at[:4]}-{report_id:05d}"


def present_report(row: sqlite3.Row) -> dict:
    report = dict(row)
    report["reference"] = reference_number(row["id"], row["created_at"])
    report["affected_list"] = [AFFECTED.get(a, a) for a in row["affected"].split(";") if a]
    report["channel_label"] = CHANNELS.get(row["channel"], row["channel"])
    report["department_label"] = pretty_department(row["department"])
    final = row["confirmed_category"] or (None if row["needs_review"] else row["predicted_category"])
    report["final_info"] = category_info(final)
    report["predicted_info"] = category_info(row["predicted_category"])
    report["status_label"] = STATUSES.get(row["status"], row["status"])
    report["alternatives"] = json.loads(row["alternatives_json"] or "[]")
    report["priority_label"] = PRIORITIES.get(row["priority"], row["priority"])
    report["editable"] = row["status"] == "received"
    return report


# --------------------------------------------------------------------------- business rules
def report_priority(result: dict, amount_lost: int | None, affected: list[str]) -> str:
    """Queue priority for the analysts, partly decided by the model output.

    High: the classifier is not confident (a person must decide), the loss is one million pesos
    or more, or a company system was affected. Medium: money or an account was affected.
    """
    if result["needs_review"] or (amount_lost or 0) >= 1_000_000 or "business_system" in affected:
        return "high"
    if amount_lost or {"money", "account"} & set(affected):
        return "medium"
    return "normal"


def timed_classification(description: str, channel: str, affected: list[str]) -> tuple[dict, float]:
    started = time.perf_counter()
    result = classify_report(description, channel, affected)
    return result, (time.perf_counter() - started) * 1000


def record_inference(connection, result: dict, inference_ms: float, source: str, channel: str,
                     description: str, report_id: int | None = None) -> None:
    """Inference history: date, user, result, confidence, model version and response time."""
    user = g.get("user")
    connection.execute(
        """INSERT INTO inferences (user_id, report_id, source, model_version, predicted_category, confidence,
           needs_review, channel, input_chars, inference_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user["id"] if user else None, report_id, source, result["model_version"], result["category"],
         result["confidence"], int(result["needs_review"]), channel, len(description), inference_ms))
    logger.info("inference source=%s category=%s confidence=%.3f ms=%.1f version=%s", source,
                result["category"], result["confidence"], inference_ms, result["model_version"])


def add_event(connection, report_id: int, action: str, detail: str = "") -> None:
    user = g.get("user")
    connection.execute("INSERT INTO report_events (report_id, actor_id, action, detail) VALUES (?, ?, ?, ?)",
                       (report_id, user["id"] if user else None, action, detail[:300]))


def report_events(report_id: int, include_actor: bool = False) -> list[dict]:
    with connect_db() as connection:
        rows = connection.execute(
            """SELECT e.action, e.detail, e.created_at, u.name AS actor, u.role AS actor_role
               FROM report_events e LEFT JOIN users u ON u.id = e.actor_id
               WHERE e.report_id = ? ORDER BY e.id""", (report_id,)).fetchall()
    events = []
    for row in rows:
        item = {"label": EVENT_LABELS.get(row["action"], row["action"]), "detail": row["detail"],
                "created_at": row["created_at"], "action": row["action"]}
        if include_actor:
            item["actor"] = f"{row['actor'] or 'Deleted account'} ({ROLES.get(row['actor_role'], '-')})"
        events.append(item)
    return events


@app.context_processor
def inject_shared_context():
    role = g.user["role"] if g.get("user") else None
    return {"project_name": "Cybercrime Colombia",
            "model_ready": model_available(),
            "current_user": (g.user["name"] or g.user["email"]) if g.get("user") else None,
            "current_role": role, "role_label": ROLES.get(role or "", ""),
            "is_analyst": bool(g.user), "is_staff": bool(g.user), "is_admin": bool(g.user),
            "csrf_token": session.setdefault("_csrf_token", secrets.token_urlsafe(32)),
            "category_info": category_info, "CATEGORY_INFO": CATEGORY_INFO,
            "common_passwords": sorted(COMMON_PASSWORDS)}


# --------------------------------------------------------------------------- public pages
@app.get("/")
def home():
    return render_template("index.html", page_title="Home", data=dataset_context())


@app.get("/business")
def business():
    return render_template("business.html", page_title="1 Â· Business and data understanding",
                           data=dataset_context(), info=get_info(), report_info=report_model_info())


@app.get("/dataset")
@staff_required
def dataset():
    return render_template("dataset.html", page_title="2 Â· Data engineering", data=dataset_context(),
                           quality=read_json(REPORTS_DIR / "data_quality.json", {}) or {},
                           info=get_info(), report_info=report_model_info())


@app.get("/territorial-analysis")
@staff_required
def territorial_analysis():
    filters = {
        "scope": request.args.get("scope", "national"),
        "department": request.args.get("department", ""),
        "municipality": request.args.get("municipality", ""),
        "basis": request.args.get("basis", "report"),
        "category": request.args.get("category", "all"),
        "compare_level": request.args.get("compare_level", "department"),
        "year": request.args.get("year", ""),
    }
    try:
        analysis = build_analysis_context(filters)
        error = None
    except (FileNotFoundError, ValueError) as exc:
        analysis, error = None, str(exc)
    return render_template("territorial_analysis.html", page_title="Cybercrime Territorial and Temporal Analysis",
                           analysis=analysis, error=error)


@app.route("/assistant", methods=["GET", "POST"])
def cybersecurity_assistant():
    result = None
    values = {"problem": "", "status": "prevention", "description": "", "exposure": []}
    if request.method == "POST":
        validate_csrf()
        values = {"problem": request.form.get("problem", "other")[:40],
                  "status": request.form.get("status", "prevention")[:20],
                  "description": request.form.get("description", "")[:2000],
                  "exposure": request.form.getlist("exposure")}
        if values["problem"] not in {"phishing", "suspicious_website", "account", "identity", "fraud", "malware", "unauthorized", "personal_data", "attack", "data_loss", "platform_fraud", "other"}:
            abort(400)
        if values["status"] not in {"prevention", "active", "post"}:
            abort(400)
        allowed_exposures = {"clicked_link", "entered_password", "shared_code", "downloaded_file",
                             "opened_file", "sent_money", "lost_account", "shared_data"}
        if not set(values["exposure"]).issubset(allowed_exposures):
            abort(400)
        result = assess_situation(values["problem"], values["description"], values["status"],
                                  values["exposure"])
    return render_template("assistant.html", page_title="Intelligent Cybersecurity Assistant",
                           result=result, values=values)


@app.get("/preprocessing")
@staff_required
def preprocessing():
    return redirect(url_for("dataset") + "#preparation", code=301)


@app.get("/models")
@staff_required
def models():
    experiments_path = REPORT_MODEL_DIR / "experiments.csv"
    experiments = (pd.read_csv(experiments_path).to_dict(orient="records")
                   if experiments_path.exists() else [])
    return render_template("models.html", page_title="3 Â· Model engineering", models=get_model_summaries(),
                           info=get_info(), report_info=report_model_info(), experiments=experiments)


@app.get("/evaluation")
@staff_required
def evaluation():
    return render_template("evaluation.html", page_title="4 Â· Model evaluation", metrics=get_metrics(),
                           report_metrics=get_report_metrics(), models=get_model_summaries(),
                           info=get_info(), report_info=report_model_info(),
                           review=read_json(REPORTS_DIR / "expert_review.json", {}) or {})


@app.route("/deployment", methods=["GET", "POST"])
def deployment():
    demo, demo_input, demo_error = None, {}, None
    if request.method == "POST":
        # Public demo of the saved model: nothing is stored.
        validate_csrf()
        demo_input = {"description": " ".join(request.form.get("description", "").split())[:600],
                      "channel": request.form.get("channel", ""),
                      "affected": [a for a in request.form.getlist("affected") if a in AFFECTED]}
        if len(demo_input["description"]) < 15 or demo_input["channel"] not in CHANNELS:
            demo_error = "Write at least 15 characters and choose a channel."
        elif not model_available():
            demo_error = "The classifier is not available right now."
        else:
            demo, inference_ms = timed_classification(
                demo_input["description"], demo_input["channel"], demo_input["affected"])
            demo["inference_ms"] = inference_ms
            with connect_db() as connection:  # only metadata is kept, never the demo text
                record_inference(connection, demo, demo["inference_ms"], "demo", demo_input["channel"],
                                 demo_input["description"])
    artifacts = []
    for path in [MODELS_DIR / "report_classifier.joblib", MODELS_DIR / "report_classifier_info.json",
                 MODELS_DIR / "report_reference_stats.json", MODELS_DIR / "best_model.joblib"]:
        if path.exists():
            artifacts.append({"name": path.relative_to(ROOT).as_posix(), "kb": round(path.stat().st_size / 1024)})
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").split()
    return render_template("deployment.html", page_title="5 Â· Deployment", report_info=report_model_info(),
                           artifacts=artifacts, requirements=requirements, channels=CHANNELS,
                           affected=AFFECTED, demo=demo, demo_input=demo_input, demo_error=demo_error)


@app.get("/monitoring")
def monitoring():
    with connect_db() as connection:
        live = dict(connection.execute(
            """SELECT COUNT(*) AS total, AVG(confidence) AS avg_confidence, AVG(inference_ms) AS avg_inference,
                      AVG(needs_review) AS low_confidence, AVG(user_agrees) AS citizen_agreement,
                      AVG(duration_seconds) AS avg_duration,
                      SUM(CASE WHEN confirmed_category IS NOT NULL THEN 1 ELSE 0 END) AS confirmed,
                      SUM(CASE WHEN confirmed_category = predicted_category THEN 1 ELSE 0 END) AS matches
               FROM incident_reports""").fetchone())
    return render_template("monitoring.html", page_title="6 Â· Monitoring and maintenance",
                           simulated=read_json(REPORTS_DIR / "monitoring/monitoring_report.json", {}) or {},
                           live=live, report_info=report_model_info())


@app.get("/system")
def system_design():
    """Public documentation of the information system: users, processes, modules, architecture and data model."""
    return render_template("system.html", page_title="System design", roles=ROLES, report_info=report_model_info(),
                           statuses=STATUSES, priorities=PRIORITIES, ticket_kinds=TICKET_KINDS)


@app.get("/help")
def user_help():
    """User manual, short training guide and the feedback and incident procedures."""
    return render_template("help.html", page_title="User manual and training")


@app.get("/reports")
@staff_required
def reports():
    return render_template("reports.html", page_title="Conclusions", info=get_info(),
                           report_info=report_model_info(), data=dataset_context())


@app.get("/reports/figure/<name>.png")
def report_figure(name: str):
    figures = {"data-quality": ("", "data_quality.png"),
               "cv-comparison": ("report_classifier", "cv_comparison.png"),
               "monitoring": ("monitoring", "monitoring.png")}
    if name not in figures:
        abort(404)
    folder, filename = figures[name]
    return send_from_directory(REPORTS_DIR / folder if folder else REPORTS_DIR, filename)


@app.get("/reports/files/<path:filename>")
@staff_required
def report_file(filename: str):
    # send_from_directory keeps manipulated names inside reports/.
    return send_from_directory(REPORTS_DIR, filename, as_attachment=filename.endswith(".md"))


@app.get("/reports/confusion/<model>.png")
@staff_required
def confusion_image(model: str):
    if model not in dict(MODELS):
        abort(404)
    return send_from_directory(CONFUSION_DIR, f"{model}.png")


@app.get("/reports/report-confusion/<model>.png")
def report_confusion_image(model: str):
    if model not in dict(MODELS):
        abort(404)
    return send_from_directory(REPORT_MODEL_DIR / "confusion_matrices", f"{model}.png")


@app.get("/reports/model-comparison.png")
@staff_required
def comparison_image():
    return send_from_directory(REPORTS_DIR, "model_comparison.png")


# --------------------------------------------------------------------------- accounts
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        validate_csrf()
        name = " ".join(request.form.get("name", "").split())
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        problem = password_problem(password, email, name)
        if not 2 <= len(name) <= 100:
            flash("Enter your name (2 to 100 characters).", "error")
        elif len(email) > 254 or not EMAIL_PATTERN.match(email):
            flash("Enter a valid email address.", "error")
        elif problem:
            flash(problem, "error")
        else:
            role = initial_role(email)  # any "role" sent by the browser is ignored
            try:
                with connect_db() as connection:
                    cursor = connection.execute(
                        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                        (name, email, hash_password(password), role))
                    user = connection.execute("SELECT id, session_version FROM users WHERE id = ?",
                                              (cursor.lastrowid,)).fetchone()
                start_session(user)
                logger.info("account created user_id=%s", user["id"])
                flash("Your account is ready.", "success")
                return redirect(safe_next(url_for("dashboard")))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists. Log in instead.", "error")
        return render_template("register.html", page_title="Create account",
                               form={"name": name, "email": email}), 400
    return render_template("register.html", page_title="Create account", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        validate_csrf()
        email = request.form.get("email", "").strip().lower()[:254]
        password = request.form.get("password", "")[:PASSWORD_MAX * 4]
        retry_after = login_retry_after(email)
        if retry_after:
            response = render_template("login.html", page_title="Log in", retry_after=retry_after,
                                       form={"email": email})
            return response, 429, {"Retry-After": str(retry_after)}
        with connect_db() as connection:
            user = connection.execute(
                "SELECT id, password_hash, session_version, active FROM users WHERE email = ? COLLATE NOCASE",
                (email,)).fetchone()
        # Always verify a hash so response time does not reveal whether the email exists.
        valid = check_password_hash(user["password_hash"] if user else DUMMY_PASSWORD_HASH, password)
        if user and valid and not user["active"]:
            logger.info("login refused for deactivated account user_id=%s", user["id"])
            flash("This account is deactivated. Contact the platform administrator.", "error")
            return render_template("login.html", page_title="Log in", form={"email": email}), 403
        if user and valid:
            clear_login_failures(email)
            if not user["password_hash"].startswith(PASSWORD_HASH_METHOD + ":"):
                # Upgrade hashes created with an older method the next time the user logs in.
                with connect_db() as connection:
                    connection.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                                       (hash_password(password), user["id"]))
            start_session(user)
            logger.info("login ok user_id=%s", user["id"])
            flash("Welcome back.", "success")
            return redirect(safe_next(url_for("dashboard")))
        record_login_failure(email)
        logger.info("login failed ip=%s", client_ip())
        flash("Incorrect email or password.", "error")
        return render_template("login.html", page_title="Log in", form={"email": email}), 401
    return render_template("login.html", page_title="Log in", form={})


@app.post("/logout")
def logout():
    validate_csrf()
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("home"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        validate_csrf()
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        with connect_db() as connection:
            stored = connection.execute("SELECT password_hash FROM users WHERE id = ?",
                                        (g.user["id"],)).fetchone()["password_hash"]
        problem = password_problem(new, g.user["email"], g.user["name"])
        if not check_password_hash(stored, current):
            flash("Your current password is not correct.", "error")
        elif problem:
            flash(problem, "error")
        elif check_password_hash(stored, new):
            flash("The new password must be different from the current one.", "error")
        else:
            with connect_db() as connection:
                connection.execute(
                    "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                    (hash_password(new), g.user["id"]))
                user = connection.execute("SELECT id, session_version FROM users WHERE id = ?",
                                          (g.user["id"],)).fetchone()
            start_session(user)  # keeps this browser signed in, signs out every other one
            flash("Password changed. Other devices were signed out.", "success")
            return redirect(url_for("account"))
        return render_template("account.html", page_title="Account"), 400
    return render_template("account.html", page_title="Account")


@app.post("/account/delete")
@login_required
def account_delete():
    """Right to deletion (Law 1581 of 2012): the citizen removes the account and its reports."""
    validate_csrf()
    with connect_db() as connection:
        stored = connection.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if not check_password_hash(stored["password_hash"], request.form.get("password", "")):
            flash("Your password is not correct. The account was not deleted.", "error")
            return redirect(url_for("account"))
        if g.user["role"] == "admin" and connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0] <= 1:
            flash("You are the only administrator. Give the role to someone else first.", "error")
            return redirect(url_for("account"))
        connection.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    logger.info("account deleted by its owner user_id=%s", g.user["id"])
    session.clear()
    flash("Your account and your reports were deleted.", "success")
    return redirect(url_for("home"))


@app.get("/dashboard")
@login_required
def dashboard():
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT * FROM incident_reports WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 3",
            (g.user["id"],)).fetchall()
        total = connection.execute("SELECT COUNT(*) FROM incident_reports WHERE user_id = ?",
                                   (g.user["id"],)).fetchone()[0]
        platform_total = connection.execute("SELECT COUNT(*) FROM incident_reports").fetchone()[0]
    return render_template("dashboard.html", page_title="Dashboard",
                           recent=[present_report(r) for r in rows], total=total,
                           platform_total=platform_total, data=dataset_context())


# --------------------------------------------------------------------------- incident reports
@app.get("/report")
def report_intro():
    return render_template("report_intro.html", page_title="Report an incident")


def parse_report_form() -> tuple[dict, list[str]]:
    form = request.form
    errors = []
    allowed = {"csrf_token", "occurred_on", "department", "municipality", "channel", "affected",
               "amount_lost", "description", "consent", "started_at"}
    if set(form) - allowed:
        errors.append("The form contains fields that are not allowed.")
    values = {"occurred_on": form.get("occurred_on", "").strip(),
              "department": form.get("department", "").strip(),
              "municipality": form.get("municipality", "").strip()[:80],
              "channel": form.get("channel", "").strip(),
              "affected": [a for a in form.getlist("affected") if a in AFFECTED],
              "amount_lost": form.get("amount_lost", "").replace(".", "").replace(",", "").strip(),
              "description": " ".join(form.get("description", "").split()),
              "consent": form.get("consent") == "yes"}
    try:
        occurred = date.fromisoformat(values["occurred_on"])
        if occurred > date.today() or occurred < date.today() - timedelta(days=365 * 5):
            errors.append("Choose a date within the last five years.")
    except ValueError:
        errors.append("Tell us when it happened.")
    if values["department"] not in dict(departments()):
        errors.append("Choose the department where it happened.")
    if values["channel"] not in CHANNELS:
        errors.append("Tell us how it started.")
    if not values["affected"]:
        errors.append("Select at least one thing that was affected.")
    if values["amount_lost"]:
        if not values["amount_lost"].isdigit() or int(values["amount_lost"]) > 10_000_000_000:
            errors.append("Write the amount in pesos using numbers only.")
    if not 15 <= len(values["description"]) <= 600:
        errors.append("Describe what happened in 15 to 600 characters.")
    if not values["consent"]:
        errors.append("We need your authorisation to process the report.")
    return values, errors


@app.route("/report/new", methods=["GET", "POST"])
@login_required
def report_new():
    values, errors = {"occurred_on": date.today().isoformat(), "affected": []}, []
    if request.method == "POST":
        validate_csrf()
        values, errors = parse_report_form()
        if not errors and not model_available():
            errors.append("The classifier is not available right now. Please try again later.")
        if not errors:
            result, inference_ms = timed_classification(values["description"], values["channel"],
                                                        values["affected"])
            amount = int(values["amount_lost"]) if values["amount_lost"] else None
            try:
                started_at = float(request.form.get("started_at", "0"))
                duration = int(time.time() - started_at)
                duration = duration if 0 < duration < 3600 else None
            except ValueError:
                duration = None
            with connect_db() as connection:
                cursor = connection.execute(
                    """INSERT INTO incident_reports (user_id, occurred_on, department, municipality,
                       channel, affected, amount_lost, description, predicted_category, confidence,
                       alternatives_json, needs_review, model_version, inference_ms, duration_seconds, priority)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (g.user["id"], values["occurred_on"], values["department"], values["municipality"],
                     values["channel"], ";".join(values["affected"]), amount,
                     values["description"], result["category"], result["confidence"],
                     json.dumps(result["alternatives"]), int(result["needs_review"]),
                     result["model_version"], inference_ms, duration,
                     report_priority(result, amount, values["affected"])))
                record_inference(connection, result, inference_ms, "report", values["channel"],
                                 values["description"], cursor.lastrowid)
                add_event(connection, cursor.lastrowid, "created",
                          f"{category_info(result['category'])['label']} ({result['confidence']:.0%})")
            return redirect(url_for("report_submitted", report_id=cursor.lastrowid))
    return render_template("report_form.html", page_title="New report", values=values,
                           errors=errors, departments=departments(), channels=CHANNELS,
                           affected=AFFECTED, today=date.today().isoformat(),
                           min_date=(date.today() - timedelta(days=365 * 5)).isoformat(),
                           started_at=int(time.time()), editing=None)


@app.route("/report/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def report_edit(report_id: int):
    """The citizen can correct a report while no analyst has started reviewing it."""
    row = own_report(report_id)
    if row["status"] != "received":
        flash("This report is already being reviewed and can no longer be edited. "
              "Open a support request if something needs to change.", "error")
        return redirect(url_for("report_submitted", report_id=report_id))
    values = {"occurred_on": row["occurred_on"], "department": row["department"],
              "municipality": row["municipality"], "channel": row["channel"],
              "affected": [a for a in row["affected"].split(";") if a],
              "amount_lost": str(row["amount_lost"] or ""), "description": row["description"], "consent": True}
    errors: list[str] = []
    if request.method == "POST":
        validate_csrf()
        values, errors = parse_report_form()
        if not errors and not model_available():
            errors.append("The classifier is not available right now. Please try again later.")
        if not errors:
            amount = int(values["amount_lost"]) if values["amount_lost"] else None
            changed = [name for name, old in (("date", row["occurred_on"]), ("department", row["department"]),
                                              ("municipality", row["municipality"]), ("channel", row["channel"]),
                                              ("affected", row["affected"]), ("amount", row["amount_lost"]),
                                              ("description", row["description"]))
                       if str(old or "") != str({"date": values["occurred_on"], "department": values["department"],
                                                 "municipality": values["municipality"],
                                                 "channel": values["channel"],
                                                 "affected": ";".join(values["affected"]),
                                                 "amount": amount, "description": values["description"]}[name] or "")]
            # A citizen who disagreed keeps the report at the top of the queue after editing it.
            keep_high = row["user_agrees"] == 0

            def priority_for(result: dict) -> str:
                return "high" if keep_high else report_priority(result, amount, values["affected"])

            with connect_db() as connection:
                if not changed:
                    flash("Nothing changed in the report.", "success")
                    return redirect(url_for("report_submitted", report_id=report_id))
                fields = (values["occurred_on"], values["department"], values["municipality"], values["channel"],
                          ";".join(values["affected"]), amount, values["description"])
                connection.execute(
                    """UPDATE incident_reports SET occurred_on = ?, department = ?, municipality = ?, channel = ?,
                       affected = ?, amount_lost = ?, description = ?, user_agrees = NULL,
                       updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND status = 'received'""",
                    (*fields, report_id, g.user["id"]))
                add_event(connection, report_id, "edited", "Changed: " + ", ".join(changed))
                if {"description", "channel", "affected"} & set(changed):
                    # The model input changed, so the report is classified again.
                    result, inference_ms = timed_classification(values["description"], values["channel"],
                                                                values["affected"])
                    connection.execute(
                        """UPDATE incident_reports SET predicted_category = ?, confidence = ?, alternatives_json = ?,
                           needs_review = ?, model_version = ?, inference_ms = ?, priority = ? WHERE id = ?""",
                        (result["category"], result["confidence"], json.dumps(result["alternatives"]),
                         int(result["needs_review"]), result["model_version"], inference_ms,
                         priority_for(result), report_id))
                    record_inference(connection, result, inference_ms, "edit", values["channel"],
                                     values["description"], report_id)
                    add_event(connection, report_id, "reclassified",
                              f"{category_info(result['category'])['label']} ({result['confidence']:.0%})")
                else:
                    connection.execute("UPDATE incident_reports SET priority = ? WHERE id = ?",
                                       (priority_for({"needs_review": row["needs_review"]}), report_id))
            flash("Your report was updated.", "success")
            return redirect(url_for("report_submitted", report_id=report_id))
    return render_template("report_form.html", page_title="Edit report", values=values, errors=errors,
                           departments=departments(), channels=CHANNELS, affected=AFFECTED,
                           today=date.today().isoformat(),
                           min_date=(date.today() - timedelta(days=365 * 5)).isoformat(),
                           started_at=int(time.time()), editing=present_report(row))


@app.post("/report/<int:report_id>/delete")
@login_required
def report_delete(report_id: int):
    """The citizen can withdraw a report that no analyst has started reviewing."""
    validate_csrf()
    row = own_report(report_id)
    if row["status"] != "received":
        flash("Reports under review are kept for the audit trail and cannot be deleted. "
              "Open a support request if you need help.", "error")
        return redirect(url_for("report_submitted", report_id=report_id))
    with connect_db() as connection:
        connection.execute("DELETE FROM incident_reports WHERE id = ? AND user_id = ? AND status = 'received'",
                           (report_id, g.user["id"]))
    logger.info("report withdrawn report=%s user_id=%s", report_id, g.user["id"])
    flash(f"Report {reference_number(report_id, row['created_at'])} was deleted.", "success")
    return redirect(url_for("my_reports"))


def own_report(report_id: int) -> sqlite3.Row:
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM incident_reports WHERE id = ? AND user_id = ?",
                                 (report_id, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    return row


@app.get("/report/<int:report_id>/submitted")
@login_required
def report_submitted(report_id: int):
    report = present_report(own_report(report_id))
    category = report["confirmed_category"] or report["predicted_category"]
    cases = department_counts().get((report["department"], category), 0)
    return render_template("report_submitted.html", page_title="Report received", report=report,
                           department_cases=cases, events=report_events(report_id))


@app.post("/report/<int:report_id>/feedback")
@login_required
def report_feedback(report_id: int):
    validate_csrf()
    own_report(report_id)
    answer = request.form.get("agrees")
    if answer not in {"yes", "no"}:
        abort(400, description="Choose yes or no.")
    with connect_db() as connection:
        connection.execute("UPDATE incident_reports SET user_agrees = ?, updated_at = CURRENT_TIMESTAMP "
                           "WHERE id = ?", (int(answer == "yes"), report_id))
        if answer == "no":
            # Disagreement sends the report to the top of the analyst queue.
            connection.execute("UPDATE incident_reports SET priority = 'high' WHERE id = ?", (report_id,))
        add_event(connection, report_id, "feedback",
                  "Agrees with the category" if answer == "yes" else "Does not agree with the category")
    flash("Thank you. Your answer helps us improve the classifier.", "success")
    return redirect(url_for("report_submitted", report_id=report_id) + "#classification")


@app.get("/my-reports")
@login_required
def my_reports():
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT * FROM incident_reports WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (g.user["id"],)).fetchall()
    return render_template("my_reports.html", page_title="My reports",
                           reports=[present_report(r) for r in rows])


@app.get("/history")
def history():
    return redirect(url_for("my_reports"), code=301)


@app.get("/prediction")
def prediction():
    return redirect(url_for("report_intro"), code=301)


# --------------------------------------------------------------------------- analyst review
PRIORITY_ORDER = "CASE r.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"


@app.get("/review")
@staff_required
def review():
    status = request.args.get("status", "open")
    category = request.args.get("category", "")
    search = request.args.get("q", "").strip()[:60]
    conditions, params = [], []
    if status in STATUSES:
        conditions.append("r.status = ?")
        params.append(status)
    elif status == "open":
        conditions.append("r.status != 'closed'")
    if category in CATEGORY_INFO:
        conditions.append("COALESCE(r.confirmed_category, r.predicted_category) = ?")
        params.append(category)
    if search:
        conditions.append("(r.description LIKE ? OR r.department LIKE ? OR CAST(r.id AS TEXT) = ?)")
        reference = re.fullmatch(r"(?:CC-\d{4}-)?0*(\d+)", search, flags=re.IGNORECASE)
        params += [f"%{search}%", f"%{search.upper()}%", reference.group(1) if reference else "-1"]
    query = "SELECT r.*, u.name AS reporter FROM incident_reports r JOIN users u ON u.id = r.user_id"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    with connect_db() as connection:
        rows = connection.execute(query + f" ORDER BY {PRIORITY_ORDER}, r.created_at ASC LIMIT 200",
                                  params).fetchall()
        stats = connection.execute(
            """SELECT COUNT(*) AS total, AVG(duration_seconds) AS avg_duration,
                      AVG(confidence) AS avg_confidence, AVG(inference_ms) AS avg_inference,
                      SUM(needs_review) AS low_confidence, AVG(user_agrees) AS agreement,
                      SUM(CASE WHEN confirmed_category IS NOT NULL THEN 1 ELSE 0 END) AS confirmed,
                      SUM(CASE WHEN confirmed_category = predicted_category THEN 1 ELSE 0 END) AS matches
               FROM incident_reports""").fetchone()
    reports_list = []
    for row in rows:
        item = present_report(row)
        item["reporter"] = row["reporter"]
        item["events"] = report_events(row["id"], include_actor=True)
        reports_list.append(item)
    return render_template("review.html", page_title="Review", reports=reports_list, stats=dict(stats),
                           status=status, statuses=STATUSES, model=report_model_info(),
                           category=category, search=search)


@app.post("/review/<int:report_id>")
@staff_required
def review_update(report_id: int):
    validate_csrf()
    status = request.form.get("status", "")
    confirmed = request.form.get("confirmed_category", "")
    note = request.form.get("analyst_note", "").strip()[:500]
    back = url_for("review", status=request.args.get("status", "open"))
    if status not in STATUSES or (confirmed and confirmed not in CATEGORY_INFO):
        abort(400, description="Choose a valid status and category.")
    if status == "closed" and not confirmed:
        flash("Confirm the category before closing a report.", "error")
        return redirect(back)
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM incident_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            abort(404)
        connection.execute(
            "UPDATE incident_reports SET status = ?, confirmed_category = ?, analyst_note = ?, reviewed_by = ?, "
            "closed_at = CASE WHEN ? = 'closed' THEN COALESCE(closed_at, CURRENT_TIMESTAMP) ELSE NULL END, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, confirmed or None, note, g.user["id"], status, report_id))
        if status != row["status"]:
            add_event(connection, report_id, "status",
                      f"{STATUSES.get(row['status'])} â†’ {STATUSES[status]}")
        if (confirmed or None) != row["confirmed_category"]:
            detail = category_info(confirmed)["label"] if confirmed else "Confirmation removed"
            if confirmed and confirmed != row["predicted_category"]:
                detail += f" (model said {category_info(row['predicted_category'])['label'].lower()})"
            add_event(connection, report_id, "category", detail)
        if note != row["analyst_note"]:
            add_event(connection, report_id, "note", note[:120] or "Note removed")
    flash(f"Report {reference_number(report_id, row['created_at'])} updated.", "success")
    return redirect(back)


@app.post("/review/<int:report_id>/delete")
@admin_required
def review_delete(report_id: int):
    """Administrators can remove a report (for example spam or a duplicate); the action is audited."""
    validate_csrf()
    reason = request.form.get("reason", "").strip()[:200]
    if len(reason) < 5:
        flash("Write the reason for deleting the report.", "error")
        return redirect(url_for("review", status="all"))
    with connect_db() as connection:
        row = connection.execute("SELECT id, created_at FROM incident_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            abort(404)
        connection.execute("DELETE FROM incident_reports WHERE id = ?", (report_id,))
        audit(connection, "report_deleted", reference_number(row["id"], row["created_at"]), reason)
    flash("Report deleted. The action was recorded in the audit log.", "success")
    return redirect(url_for("review", status="all"))


def audit(connection, action: str, target: str, detail: str = "") -> None:
    connection.execute("INSERT INTO audit_log (actor_id, action, target, detail) VALUES (?, ?, ?, ?)",
                       (g.user["id"], action, target, detail[:300]))
    logger.info("audit actor=%s action=%s target=%s", g.user["id"], action, target)


# --------------------------------------------------------------------------- business indicators
@app.get("/indicators")
@staff_required
def indicators():
    days = request.args.get("days", "90")
    days = int(days) if days in {"7", "30", "90", "365"} else 90
    since = f"-{days} days"
    with connect_db() as connection:
        def rows(sql, *args):
            return [dict(r) for r in connection.execute(sql, args).fetchall()]
        summary = dict(connection.execute(
            """SELECT COUNT(*) AS total,
                      SUM(status = 'closed') AS closed, SUM(status != 'closed') AS open,
                      SUM(priority = 'high' AND status != 'closed') AS high_open,
                      AVG(CASE WHEN closed_at IS NOT NULL
                          THEN (julianday(closed_at) - julianday(created_at)) * 24 END) AS hours_to_close,
                      SUM(amount_lost) AS amount_lost, AVG(duration_seconds) AS avg_duration,
                      SUM(confirmed_category IS NOT NULL) AS confirmed,
                      SUM(confirmed_category = predicted_category) AS matches
               FROM incident_reports WHERE created_at >= datetime('now', ?)""", (since,)).fetchone())
        by_category = rows(
            """SELECT COALESCE(confirmed_category, predicted_category) AS category, COUNT(*) AS reports,
                      SUM(amount_lost) AS amount, SUM(status = 'closed') AS closed
               FROM incident_reports WHERE created_at >= datetime('now', ?) GROUP BY 1 ORDER BY 2 DESC""", since)
        by_department = rows(
            """SELECT department, COUNT(*) AS reports, SUM(amount_lost) AS amount FROM incident_reports
               WHERE created_at >= datetime('now', ?) GROUP BY department ORDER BY 2 DESC LIMIT 10""", since)
        by_channel = rows(
            """SELECT channel, COUNT(*) AS reports FROM incident_reports
               WHERE created_at >= datetime('now', ?) GROUP BY channel ORDER BY 2 DESC""", since)
        by_week = rows(
            """SELECT strftime('%Y-W%W', created_at) AS week, COUNT(*) AS reports,
                      AVG(confidence) AS confidence FROM incident_reports
               WHERE created_at >= datetime('now', ?) GROUP BY 1 ORDER BY 1""", since)
        corrections = rows(
            """SELECT predicted_category, confirmed_category, COUNT(*) AS reports FROM incident_reports
               WHERE confirmed_category IS NOT NULL AND confirmed_category != predicted_category
                 AND created_at >= datetime('now', ?) GROUP BY 1, 2 ORDER BY 3 DESC""", since)
        tickets = dict(connection.execute(
            "SELECT COUNT(*) AS total, SUM(status != 'resolved') AS pending FROM support_tickets").fetchone())
    for item in by_department:
        item["label"] = pretty_department(item["department"])
    for item in by_channel:
        item["label"] = CHANNELS.get(item["channel"], item["channel"])
    peak = max([item["reports"] for item in by_week] or [1])
    return render_template("indicators.html", page_title="Indicators", days=days, summary=summary,
                           by_category=by_category, by_department=by_department, by_channel=by_channel,
                           by_week=by_week, peak=peak, corrections=corrections, tickets=tickets)


@app.get("/indicators/reports.csv")
@staff_required
def export_reports():
    """Anonymous export for analysis: no names, emails or free text."""
    with connect_db() as connection:
        rows = connection.execute(
            """SELECT id, created_at, occurred_on, department, channel, affected, amount_lost, predicted_category,
                      confidence, needs_review, model_version, user_agrees, status, confirmed_category, priority,
                      closed_at FROM incident_reports ORDER BY id""").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["reference", "created_at", "occurred_on", "department", "channel", "affected", "amount_lost",
                     "predicted_category", "confidence", "needs_review", "model_version", "citizen_agrees",
                     "status", "confirmed_category", "priority", "closed_at"])
    for row in rows:
        writer.writerow([reference_number(row["id"], row["created_at"]), *list(row)[1:]])
    logger.info("reports exported by user_id=%s rows=%s", g.user["id"], len(rows))
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=cybercrime_reports.csv"})


@app.get("/inferences")
@staff_required
def inference_history():
    source = request.args.get("source", "")
    with connect_db() as connection:
        params: list = []
        query = """SELECT i.*, u.name AS user_name FROM inferences i LEFT JOIN users u ON u.id = i.user_id"""
        if source in {"report", "edit", "demo"}:
            query += " WHERE i.source = ?"
            params.append(source)
        rows = [dict(r) for r in connection.execute(query + " ORDER BY i.id DESC LIMIT 200", params).fetchall()]
        versions = [dict(r) for r in connection.execute(
            "SELECT model_version, COUNT(*) AS n FROM inferences GROUP BY 1 ORDER BY 2 DESC").fetchall()]
    for row in rows:
        row["label"] = category_info(row["predicted_category"])["label"]
    return render_template("inferences.html", page_title="Inference history", rows=rows, source=source,
                           versions=versions)


# --------------------------------------------------------------------------- support and feedback
@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    form: dict = {"report_id": request.args.get("report", "")}
    with connect_db() as connection:
        my_reports_list = connection.execute(
            "SELECT id, created_at FROM incident_reports WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
    if request.method == "POST":
        validate_csrf()
        form = {"kind": request.form.get("kind", ""), "report_id": request.form.get("report_id", ""),
                "subject": " ".join(request.form.get("subject", "").split())[:120],
                "message": request.form.get("message", "").strip()[:1500]}
        own_ids = {str(r["id"]) for r in my_reports_list}
        errors = []
        if form["kind"] not in TICKET_KINDS:
            errors.append("Choose the type of request.")
        if form["report_id"] and form["report_id"] not in own_ids:
            errors.append("Choose one of your own reports or leave the field empty.")
        if not 5 <= len(form["subject"]) <= 120:
            errors.append("Write a subject of 5 to 120 characters.")
        if not 15 <= len(form["message"]) <= 1500:
            errors.append("Describe the request in 15 to 1,500 characters.")
        if re.search(r"(?i)(password|contraseÃ±a|clave)\s*[:=]", form["message"]):
            errors.append("Do not include passwords in the message.")
        if not errors:
            with connect_db() as connection:
                connection.execute(
                    "INSERT INTO support_tickets (user_id, report_id, kind, subject, message) VALUES (?, ?, ?, ?, ?)",
                    (g.user["id"], int(form["report_id"]) if form["report_id"] else None, form["kind"],
                     form["subject"], form["message"]))
            logger.info("support ticket created user_id=%s kind=%s", g.user["id"], form["kind"])
            flash("Your request was sent. You will see the answer here.", "success")
            return redirect(url_for("support"))
        for error in errors:
            flash(error, "error")
    with connect_db() as connection:
        tickets = [dict(r) for r in connection.execute(
            "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()]
    return render_template("support.html", page_title="Help and feedback", tickets=tickets, form=form,
                           kinds=TICKET_KINDS, ticket_statuses=TICKET_STATUSES,
                           my_reports=[{"id": r["id"], "reference": reference_number(r["id"], r["created_at"])}
                                       for r in my_reports_list])


@app.get("/support/manage")
@staff_required
def support_manage():
    status = request.args.get("status", "pending")
    query = ("SELECT t.*, u.name AS user_name, r.created_at AS report_created FROM support_tickets t "
             "JOIN users u ON u.id = t.user_id LEFT JOIN incident_reports r ON r.id = t.report_id")
    params: tuple = ()
    if status in TICKET_STATUSES:
        query += " WHERE t.status = ?"
        params = (status,)
    elif status == "pending":
        query += " WHERE t.status != 'resolved'"
    with connect_db() as connection:
        tickets = [dict(r) for r in connection.execute(query + " ORDER BY t.id", params).fetchall()]
    for ticket in tickets:
        ticket["reference"] = (reference_number(ticket["report_id"], ticket["report_created"])
                               if ticket["report_id"] else "")
    return render_template("support_manage.html", page_title="Support desk", tickets=tickets, status=status,
                           kinds=TICKET_KINDS, ticket_statuses=TICKET_STATUSES)


@app.post("/support/<int:ticket_id>")
@staff_required
def support_update(ticket_id: int):
    validate_csrf()
    status = request.form.get("status", "")
    response_text = request.form.get("staff_response", "").strip()[:1000]
    if status not in TICKET_STATUSES:
        abort(400, description="Choose a valid status.")
    if status == "resolved" and len(response_text) < 5:
        flash("Write an answer for the user before resolving the request.", "error")
        return redirect(url_for("support_manage"))
    with connect_db() as connection:
        updated = connection.execute(
            "UPDATE support_tickets SET status = ?, staff_response = ?, handled_by = ?, updated_at = CURRENT_TIMESTAMP, "
            "resolved_at = CASE WHEN ? = 'resolved' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id = ?",
            (status, response_text, g.user["id"], status, ticket_id)).rowcount
    if not updated:
        abort(404)
    flash(f"Request #{ticket_id} updated.", "success")
    return redirect(url_for("support_manage", status=request.args.get("status", "pending")))


# --------------------------------------------------------------------------- administration
@app.get("/admin/users")
@admin_required
def admin_users():
    search = request.args.get("q", "").strip()[:80]
    with connect_db() as connection:
        params: tuple = ()
        query = ("SELECT u.id, u.name, u.email, u.role, u.active, u.created_at, u.last_login_at, "
                 "(SELECT COUNT(*) FROM incident_reports r WHERE r.user_id = u.id) AS reports FROM users u")
        if search:
            query += " WHERE u.name LIKE ? OR u.email LIKE ?"
            params = (f"%{search}%", f"%{search}%")
        users = [dict(r) for r in connection.execute(query + " ORDER BY u.id", params).fetchall()]
        counts = {r["role"]: r["n"] for r in connection.execute(
            "SELECT role, COUNT(*) AS n FROM users WHERE active = 1 GROUP BY role")}
        log = [dict(r) for r in connection.execute(
            "SELECT a.*, u.name AS actor FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id "
            "ORDER BY a.id DESC LIMIT 15").fetchall()]
    return render_template("admin_users.html", page_title="Users and roles", users=users, roles=ROLES,
                           counts=counts, search=search, log=log)


@app.post("/admin/users/<int:user_id>")
@admin_required
def admin_user_update(user_id: int):
    validate_csrf()
    role = request.form.get("role", "")
    active = request.form.get("active") == "1"
    if role not in ROLES:
        abort(400, description="Choose a valid role.")
    if user_id == g.user["id"]:
        flash("You cannot change your own role or deactivate your own account.", "error")
        return redirect(url_for("admin_users"))
    with connect_db() as connection:
        user = connection.execute("SELECT id, email, role, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            abort(404)
        changes = []
        if role != user["role"]:
            changes.append(f"role {user['role']} â†’ {role}")
        if active != bool(user["active"]):
            changes.append("activated" if active else "deactivated")
        if changes:
            # Changing the role or deactivating also ends the user's open sessions.
            connection.execute("UPDATE users SET role = ?, active = ?, session_version = session_version + 1 "
                               "WHERE id = ?", (role, int(active), user_id))
            audit(connection, "user_updated", user["email"], ", ".join(changes))
    flash("User updated." if changes else "Nothing changed.", "success")
    return redirect(url_for("admin_users", q=request.args.get("q", "")))


@app.route("/admin/operations", methods=["GET", "POST"])
@admin_required
def admin_operations():
    days = request.args.get("days", "7")
    days = int(days) if days in {"1", "7", "30"} else 7
    with connect_db() as connection:
        metrics = operations.collect(connection, days, read_json(MODELS_DIR / "report_reference_stats.json", {}) or {})
        if request.method == "POST":
            validate_csrf()
            findings = request.form.get("findings", "").strip()[:2000]
            actions = request.form.get("actions", "").strip()[:2000]
            if len(findings) < 10 or len(actions) < 5:
                flash("Write the findings and the actions decided.", "error")
            else:
                connection.execute(
                    "INSERT INTO operational_reviews (reviewer_id, period_days, metrics_json, findings, actions) "
                    "VALUES (?, ?, ?, ?, ?)", (g.user["id"], days, json.dumps(metrics, default=str), findings, actions))
                flash("Operational review saved with a snapshot of the indicators.", "success")
                return redirect(url_for("admin_operations", days=days))
        reviews = [dict(r) for r in connection.execute(
            "SELECT o.*, u.name AS reviewer FROM operational_reviews o LEFT JOIN users u ON u.id = o.reviewer_id "
            "ORDER BY o.id DESC LIMIT 10").fetchall()]
        registry = [dict(r) for r in connection.execute(
            "SELECT * FROM model_versions ORDER BY active DESC, registered_at DESC").fetchall()]
    for row in registry:
        metrics_json = json.loads(row["metrics_json"] or "{}")
        row["holdout_accuracy"] = metrics_json.get("holdout_accuracy")
        row["cv_f1"] = metrics_json.get("cv_f1_macro_mean")
    for review_row in reviews:
        review_row["snapshot"] = json.loads(review_row["metrics_json"])
    return render_template("admin_operations.html", page_title="Operations", days=days, m=metrics,
                           reviews=reviews, registry=registry, thresholds=operations.THRESHOLDS)


@app.get("/healthz")
def healthz():
    """Health check for Render and for the deployment smoke test (no personal data)."""
    try:
        with connect_db() as connection:
            connection.execute("SELECT 1").fetchone()
        database = "ok"
    except sqlite3.Error:
        database = "error"
    status = "ok" if database == "ok" and model_available() else "degraded"
    return jsonify(status=status, database=database, model_available=model_available(),
                   model_version=f"{report_model_info().get('algorithm', '-')}@{report_model_info().get('version', '-')}"), \
        200 if status == "ok" else 503


# --------------------------------------------------------------------------- CLI
@app.cli.command("set-role")
@click.argument("email")
@click.argument("role", type=click.Choice(sorted(ROLES)))
def set_role(email: str, role: str):
    """Give a role (citizen, analyst or admin) to an existing account."""
    ensure_database()
    with connect_db() as connection:
        changed = connection.execute(
            "UPDATE users SET role = ?, session_version = session_version + 1 WHERE email = ? COLLATE NOCASE",
            (role, email.strip())).rowcount
    click.echo(f"{email} is now {ROLES[role].lower()}." if changed else f"No account found for {email}.")


@app.cli.command("make-analyst")
@click.argument("email")
@click.pass_context
def make_analyst(ctx, email: str):
    """Give the analyst role to an existing account (shortcut for set-role EMAIL analyst)."""
    ctx.invoke(set_role, email=email, role="analyst")


@app.cli.command("create-user")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
@click.option("--role", type=click.Choice(sorted(ROLES)), default="citizen", show_default=True)
@click.password_option()
def create_user(name: str, email: str, role: str, password: str):
    """Create an account with a role, for example the private test accounts for each role."""
    ensure_database()
    email = email.strip().lower()
    problem = password_problem(password, email, name)
    if problem or not EMAIL_PATTERN.match(email):
        raise click.ClickException(problem or "Invalid email address.")
    try:
        with connect_db() as connection:
            connection.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                               (" ".join(name.split()), email, hash_password(password), role))
    except sqlite3.IntegrityError as exc:
        raise click.ClickException("An account with that email already exists.") from exc
    click.echo(f"Account {email} created with role {role}.")


@app.cli.command("backup-db")
@click.argument("destination", type=click.Path(dir_okay=False))
def backup_db(destination: str):
    """Copy the live SQLite database to DESTINATION with the online backup API."""
    ensure_database()
    target = sqlite3.connect(destination)
    source = sqlite3.connect(USER_DB_PATH)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    click.echo(f"Database copied to {destination}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")

