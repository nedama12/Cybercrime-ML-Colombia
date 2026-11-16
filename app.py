"""Plataforma Flask para explorar el dataset y demostrar los modelos ML."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import secrets
import sqlite3
import hmac
import csv
import io
import time
from collections import defaultdict, deque
from functools import lru_cache
from functools import wraps
from pathlib import Path
from datetime import timedelta

import pandas as pd
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, session, url_for, Response)
import click
from werkzeug.security import check_password_hash, generate_password_hash

from src.predict import MODEL_PATH, predict_incident
from src.phishing_predict import MODEL_PATH as PHISHING_MODEL_PATH, INFO_PATH as PHISHING_INFO_PATH, predict_url
from src.territorial_analysis import build_analysis_context
from src.cybersecurity_guidance import assess_situation
from src.report_model import classify_report, category_info as report_category_info, model_available as report_model_available

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data/processed/delitos_procesado.csv"
REPORTS_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"
METRICS_PATH = REPORTS_DIR / "model_comparison.csv"
INFO_PATH = MODELS_DIR / "best_model_info.json"
CLASS_REPORT_DIR = REPORTS_DIR / "classification_reports"
CONFUSION_DIR = REPORTS_DIR / "confusion_matrices"
INSTANCE_DIR = ROOT / "instance"
USER_DB_PATH = Path(os.environ.get("USER_DB_PATH", str(INSTANCE_DIR / "cybercrime.sqlite3")))
SECRET_KEY_PATH = INSTANCE_DIR / "flask_secret_key"
LOGIN_ATTEMPT_WINDOW_SECONDS = 10 * 60
LOGIN_LOCK_SECONDS = 2 * 60
LOGIN_MAX_FAILURES = 5
USER_ROLES = {"admin", "analyst", "user"}
INCIDENT_CATEGORIES = {"Phishing", "Account Theft", "Banking or Transfer Fraud", "Malware",
                       "Identity Impersonation", "Suspicious Website", "Other Cybersecurity Incident"}
INCIDENT_STATES = {"Open", "Under Review", "In Progress", "Resolved", "Closed"}
_login_failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_login_blocked_until: dict[tuple[str, str], float] = {}
logger = logging.getLogger(__name__)


def load_secret_key() -> str:
    configured = os.environ.get("FLASK_SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("FLASK_SECRET_KEY must contain at least 32 characters.")
        return configured
    if os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("FLASK_SECRET_KEY is required in production.")
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_KEY_PATH.exists():
        SECRET_KEY_PATH.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return SECRET_KEY_PATH.read_text(encoding="utf-8").strip()

app = Flask(__name__)
app.secret_key = load_secret_key()
app.permanent_session_lifetime = timedelta(hours=8)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1")
app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(hours=8), SESSION_REFRESH_EACH_REQUEST=True)


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


def ensure_user_database() -> None:
    with connect_db() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "name" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "role" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "is_active" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        connection.execute("""CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            incident_json TEXT NOT NULL,
            category TEXT NOT NULL,
            probabilities_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_predictions_user_created "
                           "ON predictions(user_id, created_at DESC)")
        connection.execute("""CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            occurred_at TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            analyst_notes TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT 'unknown',
            affected_json TEXT NOT NULL DEFAULT '[]',
            predicted_category TEXT,
            prediction_confidence REAL,
            alternatives_json TEXT NOT NULL DEFAULT '[]',
            model_version TEXT,
            needs_review INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        # Backward-compatible migration for existing SQLite databases.
        incident_columns = {row["name"] for row in connection.execute("PRAGMA table_info(incidents)")}
        incident_migrations = {
            "channel": "TEXT NOT NULL DEFAULT 'unknown'",
            "affected_json": "TEXT NOT NULL DEFAULT '[]'",
            "predicted_category": "TEXT",
            "prediction_confidence": "REAL",
            "alternatives_json": "TEXT NOT NULL DEFAULT '[]'",
            "model_version": "TEXT",
            "needs_review": "INTEGER NOT NULL DEFAULT 1",
        }
        for column, definition in incident_migrations.items():
            if column not in incident_columns:
                connection.execute(f"ALTER TABLE incidents ADD COLUMN {column} {definition}")
        connection.execute("""CREATE TABLE IF NOT EXISTS incident_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_incidents_user_created "
                           "ON incidents(user_id, created_at DESC)")


@app.cli.command("promote-admin")
@click.argument("email")
def promote_admin_command(email: str) -> None:
    """Grant admin to an existing account from a trusted deployment shell."""
    ensure_user_database()
    with connect_db() as connection:
        row = connection.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
        if row is None:
            raise click.ClickException("Create the account first, then run this command.")
        connection.execute("UPDATE users SET role = 'admin', is_active = 1 WHERE id = ?", (row["id"],))
    click.echo(f"Administrator role granted to {email}.")


def save_prediction(user_id: int, incident: dict, result: dict) -> int:
    model_key = incident.get("_model", "cybercrime")
    if model_key == "phishing":
        metadata = read_json(PHISHING_INFO_PATH, {}) or {}
        training = metadata.get("scikit_learn_version", "unknown")
        dataset_hash = (metadata.get("dataset", {}) or {}).get("sha256", "")[:12]
        version = f"sklearn-{training}/data-{dataset_hash or 'unspecified'}"
    else:
        metadata = get_info()
        version = str(metadata.get("training_date_utc") or metadata.get("algorithm") or "unknown")
    incident.setdefault("_model_version", version)
    with connect_db() as connection:
        cursor = connection.execute(
            "INSERT INTO predictions (user_id, incident_json, category, probabilities_json) "
            "VALUES (?, ?, ?, ?)",
            (user_id, json.dumps(incident, ensure_ascii=False), result["prediction"],
             json.dumps(result.get("probabilities", {}), ensure_ascii=False)))
        return int(cursor.lastrowid)


def current_user_email() -> str | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with connect_db() as connection:
        row = connection.execute("SELECT name, email, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not row["is_active"]:
        session.clear()
        return None
    return str(row["name"] or row["email"])


def current_user_role() -> str | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with connect_db() as connection:
        row = connection.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not row["is_active"]:
        session.clear()
        return None
    return str(row["role"] or "user")


def _login_key(email: str) -> tuple[str, str]:
    return email.casefold(), request.remote_addr or "unknown"


def _login_retry_after(key: tuple[str, str]) -> int:
    now = time.monotonic()
    blocked_until = _login_blocked_until.get(key, 0)
    if blocked_until > now:
        return max(1, int(blocked_until - now + 0.999))
    _login_blocked_until.pop(key, None)
    attempts = _login_failures[key]
    while attempts and now - attempts[0] >= LOGIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        _login_failures.pop(key, None)
    return 0


def _record_login_failure(key: tuple[str, str]) -> None:
    now = time.monotonic()
    attempts = _login_failures[key]
    attempts.append(now)
    while attempts and now - attempts[0] >= LOGIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_FAILURES:
        _login_blocked_until[key] = now + LOGIN_LOCK_SECONDS


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    logger.exception("SQLite database error", exc_info=error)
    return "The operation could not be completed. Please try again later.", 503


@app.before_request
def prepare_user_database():
    ensure_user_database()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            flash("Sign in to submit a prediction.", "error")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        with connect_db() as connection:
            active = connection.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
        if active is None or not active["is_active"]:
            session.clear()
            flash("This account is unavailable. Contact an administrator.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                flash("Sign in to access this page.", "error")
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            role = current_user_role()
            if role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


analyst_required = roles_required("analyst", "admin")
admin_required = roles_required("admin")


def validate_csrf() -> None:
    expected = session.get("_csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="The form expired or the security token is invalid. Reload the page.")


@lru_cache(maxsize=1)
def get_dataset() -> pd.DataFrame:
    if not DATA_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(DATA_PATH)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
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


def get_model_summaries() -> list[dict]:
    metadata = get_info()
    best = metadata.get("algorithm")
    summaries = []
    for key, title, description in [
        ("decision_tree", "Decision Tree", "Builds hierarchical rules by splitting the data according to its features."),
        ("random_forest", "Random Forest", "Combines trees trained on samples and feature subsets."),
        ("logistic_regression", "Logistic Regression", "Estimates class probabilities using a multiclass logistic function."),
    ]:
        report = read_json(CLASS_REPORT_DIR / f"{key}.json", {}) or {}
        metric = next((row for row in get_metrics() if row.get("model") == key), {})
        summaries.append({"key": key, "title": title, "description": description,
                          "best": key == best, "metrics": metric, "report": report,
                          "parameters": metadata.get("parameters", {}) if key == best else {}})
    return summaries


def prediction_report_rows() -> list[dict]:
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT p.id,p.user_id,p.incident_json,p.category,p.created_at,u.email "
            "FROM predictions p JOIN users u ON u.id=p.user_id "
            "ORDER BY p.created_at DESC,p.id DESC").fetchall()
    results = []
    for row in rows:
        incident = json.loads(row["incident_json"])
        model_key = incident.pop("_model", "cybercrime")
        version = incident.pop("_model_version", "Unknown")
        results.append({"id": row["id"], "user_id": row["user_id"], "email": row["email"],
                        "created_at": row["created_at"], "analysis": model_key,
                        "category": row["category"], "model_version": version,
                        "department": incident.get("departamento_hecho", ""),
                        "municipality": incident.get("municipio_hecho", "")})
    return results


def activity_report_context() -> dict:
    rows = prediction_report_rows()
    phishing = [row for row in rows if row["analysis"] == "phishing"]
    crime = [row for row in rows if row["analysis"] != "phishing"]
    category_counts: dict[str, int] = defaultdict(int)
    month_counts: dict[str, int] = defaultdict(int)
    territory_counts: dict[str, int] = defaultdict(int)
    user_counts: dict[str, int] = defaultdict(int)
    for row in crime:
        category_counts[row["category"]] += 1
        place = ", ".join(str(value) for value in (row["department"], row["municipality"]) if value)
        if place:
            territory_counts[place] += 1
    for row in rows:
        month_counts[str(row["created_at"])[:7]] += 1
        user_counts[row["email"]] += 1
    report = {"total_analyses": len(rows), "phishing_count": len(phishing),
              "crime_count": len(crime),
              "categories": sorted(({"name": k, "count": v} for k, v in category_counts.items()),
                                   key=lambda item: (-item["count"], item["name"])),
              "months": sorted(({"month": k, "count": v} for k, v in month_counts.items()),
                               key=lambda item: item["month"], reverse=True)[:12],
              "territories": sorted(({"name": k, "count": v} for k, v in territory_counts.items()),
                                    key=lambda item: (-item["count"], item["name"]))[:15],
              "users": sorted(({"email": k, "count": v} for k, v in user_counts.items()),
                              key=lambda item: (-item["count"], item["email"]))}
    for key in ("categories", "months", "territories", "users"):
        peak = max((item["count"] for item in report[key]), default=0)
        for item in report[key]:
            item["percent"] = 100 * item["count"] / peak if peak else 0
    return report


def dataset_context() -> dict:
    df = get_dataset()
    if df.empty:
        return {"available": False, "rows": 0, "columns": [], "distribution": [], "sample": []}
    target = "categoria" if "categoria" in df else None
    distribution = []
    if target:
        distribution = [{"category": str(k), "count": int(v)}
                        for k, v in df[target].value_counts(dropna=False).items()]
    columns = [{"name": col, "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()), "unique": int(df[col].nunique(dropna=True))}
               for col in df.columns]
    sample = df.head(10).fillna("").astype(str).to_dict(orient="records")
    return {"available": True, "rows": len(df), "column_count": len(df.columns),
            "columns": columns, "distribution": distribution, "sample": sample,
            "target": target, "missing_total": int(df.isna().sum().sum()),
            "duplicates": int(df.duplicated().sum())}


@app.context_processor
def inject_shared_context():
    return {"project_name": "Cybercrime-ML-Colombia",
            "model_ready": MODEL_PATH.exists() and INFO_PATH.exists(),
            "phishing_model_ready": PHISHING_MODEL_PATH.exists(),
            "current_user": current_user_email(),
            "current_role": current_user_role(),
            "csrf_token": session.setdefault("_csrf_token", secrets.token_urlsafe(32))}


@app.get("/")
def home():
    return render_template("index.html", page_title="Home")


@app.get("/dashboard")
@login_required
def dashboard():
    data = dataset_context()
    info = get_info()
    with connect_db() as connection:
        prediction_count = connection.execute(
            "SELECT COUNT(*) FROM predictions WHERE user_id = ?", (session["user_id"],)
        ).fetchone()[0]
    return render_template("dashboard.html", page_title="Dashboard", data=data, info=info,
                           metrics=get_metrics(), prediction_count=prediction_count)


@app.get("/admin/users")
@admin_required
def admin_users():
    with connect_db() as connection:
        users = connection.execute(
            "SELECT id, name, email, role, is_active, created_at FROM users ORDER BY created_at, id"
        ).fetchall()
    return render_template("admin_users.html", page_title="User Administration", users=users,
                           roles=sorted(USER_ROLES))


@app.post("/admin/users/<int:user_id>")
@admin_required
def update_user(user_id: int):
    validate_csrf()
    role = request.form.get("role", "")
    active = request.form.get("is_active", "") == "1"
    if role not in USER_ROLES or request.form.get("is_active") not in {"0", "1"}:
        abort(400)
    with connect_db() as connection:
        target = connection.execute("SELECT id, role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            abort(404)
        if target["role"] == "admin" and target["is_active"] and (role != "admin" or not active):
            other_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?",
                (user_id,)).fetchone()[0]
            if not other_admins:
                flash("The last active administrator cannot be demoted or disabled.", "error")
                return redirect(url_for("admin_users"))
        connection.execute("UPDATE users SET role = ?, is_active = ? WHERE id = ?",
                           (role, int(active), user_id))
    flash("User access updated.", "success")
    return redirect(url_for("admin_users"))


INCIDENT_CHANNELS = {
    "phone_call": "Phone call", "sms_whatsapp": "Text message or WhatsApp",
    "email": "Email", "social_media": "Social media", "website_app": "Website or app",
    "device": "Phone or computer", "unknown": "I am not sure",
}
INCIDENT_AFFECTED = {
    "money": "Money", "account": "An online account", "personal_data": "Personal data",
    "device": "A phone or computer", "business_system": "A company system or website",
}


@app.route("/incidents", methods=["GET", "POST"])
@login_required
def incidents():
    if request.method == "POST":
        validate_csrf()
        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()
        occurred_at = request.form.get("occurred_at", "").strip()
        channel = request.form.get("channel", "unknown")
        affected = request.form.getlist("affected")
        if category not in INCIDENT_CATEGORIES:
            abort(400, description="Choose a valid incident category.")
        if not 20 <= len(description) <= 4000:
            abort(400, description="Describe the incident in 20 to 4,000 characters.")
        if channel not in INCIDENT_CHANNELS:
            abort(400, description="Choose a valid incident channel.")
        if not set(affected).issubset(INCIDENT_AFFECTED):
            abort(400, description="Choose valid affected elements.")
        if occurred_at:
            try:
                from datetime import date
                date.fromisoformat(occurred_at)
            except ValueError:
                abort(400, description="Enter a valid incident date.")

        classification = None
        if report_model_available():
            try:
                classification = classify_report(description, channel, affected)
            except (ValueError, OSError, RuntimeError, ImportError):
                logger.exception("Incident report classification failed")

        predicted = classification["category"] if classification else None
        confidence = classification["confidence"] if classification else None
        alternatives = classification["alternatives"] if classification else []
        model_version = classification["model_version"] if classification else None
        needs_review = bool(classification is None or classification["needs_review"])
        initial_status = "Under Review" if needs_review else "Open"
        if classification:
            note = ("Automated classification: "
                    f"{report_category_info(predicted)['label']} ({confidence:.1%} confidence).")
            if needs_review:
                note += " Analyst review required because confidence is low."
        else:
            note = "Automated classification unavailable. Analyst review required."

        with connect_db() as connection:
            cursor = connection.execute(
                """INSERT INTO incidents
                   (user_id,category,description,occurred_at,channel,affected_json,
                    predicted_category,prediction_confidence,alternatives_json,model_version,
                    needs_review,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["user_id"], category, description, occurred_at or None, channel,
                 json.dumps(affected), predicted, confidence, json.dumps(alternatives),
                 model_version, int(needs_review), initial_status))
            incident_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO incident_updates(incident_id,user_id,status,note) VALUES(?,?,?,?)",
                (incident_id, session["user_id"], initial_status, note))
        if classification:
            flash("Incident recorded and classified. Review the suggested category and recommendations.", "success")
        else:
            flash("Incident recorded. Automatic classification was unavailable, so an analyst must review it.", "warning")
        return redirect(url_for("incident_detail", incident_id=incident_id))

    role = current_user_role()
    with connect_db() as connection:
        if role in {"admin", "analyst"}:
            rows = connection.execute(
                "SELECT i.*, u.name AS reporter_name, u.email AS reporter_email FROM incidents i "
                "JOIN users u ON u.id=i.user_id ORDER BY i.updated_at DESC, i.id DESC").fetchall()
        else:
            rows = connection.execute(
                "SELECT i.*, u.name AS reporter_name, u.email AS reporter_email FROM incidents i "
                "JOIN users u ON u.id=i.user_id WHERE i.user_id=? ORDER BY i.updated_at DESC, i.id DESC",
                (session["user_id"],)).fetchall()
    return render_template("incidents.html", page_title="Incident Management", incidents=rows,
                           categories=sorted(INCIDENT_CATEGORIES), channels=INCIDENT_CHANNELS,
                           affected_options=INCIDENT_AFFECTED)


@app.get("/incidents/<int:incident_id>")
@login_required
def incident_detail(incident_id: int):
    role = current_user_role()
    with connect_db() as connection:
        incident = connection.execute(
            "SELECT i.*, u.name AS reporter_name, u.email AS reporter_email FROM incidents i "
            "JOIN users u ON u.id=i.user_id WHERE i.id=?", (incident_id,)).fetchone()
        if incident is None:
            abort(404)
        if role == "user" and incident["user_id"] != session["user_id"]:
            abort(404)
        updates = connection.execute(
            "SELECT x.*, u.name AS actor_name, u.email AS actor_email FROM incident_updates x "
            "JOIN users u ON u.id=x.user_id WHERE x.incident_id=? ORDER BY x.created_at, x.id",
            (incident_id,)).fetchall()
    incident_data = dict(incident)
    incident_data["affected"] = json.loads(incident["affected_json"] or "[]")
    incident_data["alternatives"] = json.loads(incident["alternatives_json"] or "[]")
    incident_data["prediction_info"] = (report_category_info(incident["predicted_category"])
                                        if incident["predicted_category"] else None)
    incident_data["alternative_info"] = [
        {"label": report_category_info(item["category"])["label"],
         "probability": item["probability"]}
        for item in incident_data["alternatives"]
    ]
    return render_template("incident_detail.html", page_title="Incident Detail", incident=incident_data,
                           updates=updates, states=sorted(INCIDENT_STATES),
                           can_review=role in {"admin", "analyst"},
                           channels=INCIDENT_CHANNELS, affected_options=INCIDENT_AFFECTED)


@app.post("/incidents/<int:incident_id>/review")
@analyst_required
def review_incident(incident_id: int):
    validate_csrf()
    status = request.form.get("status", "")
    note = request.form.get("note", "").strip()
    if status not in INCIDENT_STATES or len(note) > 2000:
        abort(400)
    with connect_db() as connection:
        exists = connection.execute("SELECT id FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if exists is None:
            abort(404)
        connection.execute("UPDATE incidents SET status=?, analyst_notes=?, needs_review=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (status, note, int(status == "Under Review"), incident_id))
        connection.execute("INSERT INTO incident_updates(incident_id,user_id,status,note) VALUES(?,?,?,?)",
                           (incident_id, session["user_id"], status, note))
    flash("Incident workflow updated.", "success")
    return redirect(url_for("incident_detail", incident_id=incident_id))


@app.get("/dataset")
@analyst_required
def dataset():
    data = dataset_context()
    return render_template("dataset.html", page_title="Dataset", data=data)


@app.get("/territorial-analysis")
@analyst_required
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
@analyst_required
def preprocessing():
    info = get_info()
    data = dataset_context()
    return render_template("preprocessing.html", page_title="Data Preparation", info=info, data=data)


@app.get("/models")
@analyst_required
def models():
    return render_template("models.html", page_title="Models", models=get_model_summaries(), info=get_info())


@app.get("/evaluation")
@analyst_required
def evaluation():
    return render_template("evaluation.html", page_title="Evaluation", metrics=get_metrics(),
                           models=get_model_summaries(), info=get_info())


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("prediction"))
    if request.method == "POST":
        validate_csrf()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or len(name) > 100:
            flash("Enter a name up to 100 characters.", "error")
        elif len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("The password must contain at least 8 characters.", "error")
        elif len(password) > 256:
            flash("The password is too long.", "error")
        else:
            try:
                with connect_db() as connection:
                    cursor = connection.execute(
                        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'user')",
                        (name, email, generate_password_hash(password)))
                session.clear()
                session["user_id"] = cursor.lastrowid
                session.permanent = True
                flash("Account created. You can now submit a prediction.", "success")
                return redirect(url_for("prediction"))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists.", "error")
    return render_template("register.html", page_title="Create account")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("prediction"))
    if request.method == "POST":
        validate_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = _login_key(email)
        retry_after = _login_retry_after(key)
        if retry_after:
            response = render_template("login.html", page_title="Sign in",
                                       retry_after=retry_after)
            return response, 429, {"Retry-After": str(retry_after)}
        with connect_db() as connection:
            user = connection.execute(
                "SELECT id, email, password_hash, is_active FROM users WHERE email = ? COLLATE NOCASE",
                (email,)).fetchone()
        _record_login_failure(key)
        if user and user["is_active"] and check_password_hash(user["password_hash"], password):
            _login_failures.pop(key, None)
            _login_blocked_until.pop(key, None)
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            flash("Signed in.", "success")
            destination = request.args.get("next", "")
            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)
            return redirect(url_for("prediction"))
        flash("Incorrect email or password.", "error")
    return render_template("login.html", page_title="Sign in")


@app.post("/logout")
def logout():
    validate_csrf()
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("home"))


@app.get("/history")
@login_required
def history():
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT id, incident_json, category, probabilities_json, created_at "
            "FROM predictions WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (session["user_id"],)).fetchall()
    entries = []
    for row in rows:
        probabilities = json.loads(row["probabilities_json"])
        incident = json.loads(row["incident_json"])
        model_key = incident.pop("_model", "cybercrime")
        model_version = incident.pop("_model_version", "Unknown")
        entries.append({"id": row["id"], "incident": incident,
                        "model_title": "Phishing Detection" if model_key == "phishing" else "Cybercrime Analysis",
                        "model_version": model_version,
                        "category": row["category"],
                        "probabilities": sorted(
                            [{"name": name, "value": value} for name, value in probabilities.items()],
                            key=lambda item: item["value"], reverse=True),
                        "created_at": row["created_at"]})
    return render_template("history.html", page_title="My History", predictions=entries)


def form_fields() -> list[dict]:
    info = get_info()
    features = info.get("features", [])
    df = get_dataset()
    fields = []
    for name in features:
        numeric = name in ("criminalidad", "ano_hechos", "ano_entrada", "ano_denuncia", "anio_parcial")
        options = []
        minimum = maximum = None
        if numeric and not df.empty and name in df:
            minimum, maximum = int(df[name].min()), int(df[name].max())
        if not numeric and not df.empty and name in df:
            options = sorted(str(value) for value in df[name].dropna().unique())
        if name == "anio_parcial":
            minimum, maximum = 0, 1
        if name == "criminalidad":
            minimum, maximum = 0, 1
        fields.append({"name": name, "numeric": numeric, "options": options,
                       "minimum": minimum, "maximum": maximum})
    return fields


@app.route("/prediction", methods=["GET", "POST"])
@login_required
def prediction():
    model_key = request.values.get("model", "cybercrime")
    if model_key not in {"cybercrime", "phishing"}:
        abort(400)
    fields = form_fields() if model_key == "cybercrime" else []
    result = None
    form_values = request.form.to_dict() if request.method == "POST" else {}
    error = None
    if request.method == "POST":
        validate_csrf()
        try:
            if model_key == "phishing":
                unexpected_fields = set(request.form) - {"csrf_token", "model", "url"}
                if unexpected_fields:
                    raise ValueError("The form contains unexpected fields.")
                result = predict_url(request.form.get("url", ""))
                incident = {"_model": "phishing", "url": result["input_url"]}
                result["record_id"] = save_prediction(session["user_id"], incident, result)
            else:
                incident = {}
                allowed_fields = {field["name"] for field in fields}
                unexpected_fields = set(request.form) - allowed_fields - {"csrf_token", "model"}
                if unexpected_fields:
                    raise ValueError("The form contains unexpected fields.")
                for field in fields:
                    name = field["name"]
                    raw = request.form.get(name, "").strip()
                    if not raw:
                        raise ValueError(f"The {name} field is required.")
                    if field["numeric"]:
                        try:
                            incident[name] = int(raw)
                        except ValueError as exc:
                            raise ValueError(f"The {name} field must be an integer.") from exc
                        if field["minimum"] is not None and not field["minimum"] <= incident[name] <= field["maximum"]:
                            raise ValueError(f"The {name} field must be between {field['minimum']} and {field['maximum']}.")
                    else:
                        if raw not in field["options"]:
                            raise ValueError(f"Select a valid option for {name}.")
                        incident[name] = raw
                result = predict_incident(incident)
                result["record_id"] = save_prediction(session["user_id"], incident, result)
        except (ValueError, OSError, RuntimeError) as exc:
            error = str(exc)
        except sqlite3.Error:
            result = None
            error = "The prediction was generated, but could not be saved to your history. Please try again."
    phishing_mode = model_key == "phishing"
    return render_template(
        "prediction.html",
        page_title="Phishing Detection" if phishing_mode else "Cybercrime Analysis",
        fields=fields, result=result, error=error, form_values=form_values,
        info={} if phishing_mode else get_info(), active_model=model_key)


@app.get("/reports")
@analyst_required
def reports():
    info = get_info()
    data = dataset_context()
    return render_template("reports.html", page_title="Reports", info=info, data=data,
                           metrics=get_metrics(), activity=activity_report_context())


@app.get("/reports/export.csv")
@analyst_required
def export_activity_report():
    rows = prediction_report_rows()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=("id", "created_at", "analysis", "category",
                                               "model_version", "email", "department", "municipality"))
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=activity-report.csv"})


@app.get("/reports/files/<path:filename>")
@analyst_required
def report_file(filename: str):
    # send_from_directory evita que nombres manipulados salgan de reports/.
    return send_from_directory(REPORTS_DIR, filename, as_attachment=filename.endswith(".md"))


@app.get("/reports/confusion/<model>.png")
@analyst_required
def confusion_image(model: str):
    if model not in {"decision_tree", "random_forest", "logistic_regression"}:
        abort(404)
    return send_from_directory(CONFUSION_DIR, f"{model}.png")


@app.get("/reports/model-comparison.png")
@analyst_required
def comparison_image():
    return send_from_directory(REPORTS_DIR, "model_comparison.png")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
