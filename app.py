"""Cybercrime Colombia: citizen incident reporting platform with machine learning.

Citizens register, report a cybercrime incident in about 90 seconds, receive the
category identified by the report classifier and clear next steps. Analysts
review every report, confirm or correct the category and close the case; the
confirmed reports become new training data.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sqlite3
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlsplit

import click
import pandas as pd
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from src.report_features import AFFECTED, CHANNELS
from src.report_model import (CATEGORY_INFO, category_info, classify_report, load_model, model_available,
                              model_info as report_model_info)

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


def ensure_database() -> None:
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


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    logger.exception("SQLite database error", exc_info=error)
    return render_template("error.html", page_title="Service unavailable",
                           message="We could not complete the operation. Please try again later."), 503


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
    ensure_database()
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        with connect_db() as connection:
            user = connection.execute(
                "SELECT id, name, email, role, session_version FROM users WHERE id = ?",
                (user_id,)).fetchone()
        # A password change bumps session_version and signs out every other session.
        if user is None or session.get("session_version") != user["session_version"]:
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
    return response


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


def analyst_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "analyst":
            abort(404)
        return view(*args, **kwargs)
    return wrapped


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
    return report


@app.context_processor
def inject_shared_context():
    return {"project_name": "Cybercrime Colombia",
            "model_ready": model_available(),
            "current_user": (g.user["name"] or g.user["email"]) if g.get("user") else None,
            "is_analyst": bool(g.get("user") and g.user["role"] == "analyst"),
            "csrf_token": session.setdefault("_csrf_token", secrets.token_urlsafe(32)),
            "category_info": category_info, "CATEGORY_INFO": CATEGORY_INFO,
            "common_passwords": sorted(COMMON_PASSWORDS)}


# --------------------------------------------------------------------------- public pages
@app.get("/")
def home():
    return render_template("index.html", page_title="Home", data=dataset_context())


@app.get("/business")
def business():
    return render_template("business.html", page_title="1 · Business and data understanding",
                           data=dataset_context(), info=get_info(), report_info=report_model_info())


@app.get("/dataset")
def dataset():
    return render_template("dataset.html", page_title="2 · Data engineering", data=dataset_context(),
                           quality=read_json(REPORTS_DIR / "data_quality.json", {}) or {},
                           info=get_info(), report_info=report_model_info())


@app.get("/preprocessing")
def preprocessing():
    return redirect(url_for("dataset") + "#preparation", code=301)


@app.get("/models")
def models():
    experiments_path = REPORT_MODEL_DIR / "experiments.csv"
    experiments = (pd.read_csv(experiments_path).to_dict(orient="records")
                   if experiments_path.exists() else [])
    return render_template("models.html", page_title="3 · Model engineering", models=get_model_summaries(),
                           info=get_info(), report_info=report_model_info(), experiments=experiments)


@app.get("/evaluation")
def evaluation():
    return render_template("evaluation.html", page_title="4 · Model evaluation", metrics=get_metrics(),
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
        else:
            started = time.perf_counter()
            demo = classify_report(demo_input["description"], demo_input["channel"], demo_input["affected"])
            demo["inference_ms"] = (time.perf_counter() - started) * 1000
    artifacts = []
    for path in [MODELS_DIR / "report_classifier.joblib", MODELS_DIR / "report_classifier_info.json",
                 MODELS_DIR / "report_reference_stats.json", MODELS_DIR / "best_model.joblib"]:
        if path.exists():
            artifacts.append({"name": path.relative_to(ROOT).as_posix(), "kb": round(path.stat().st_size / 1024)})
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").split()
    return render_template("deployment.html", page_title="5 · Deployment", report_info=report_model_info(),
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
    return render_template("monitoring.html", page_title="6 · Monitoring and maintenance",
                           simulated=read_json(REPORTS_DIR / "monitoring/monitoring_report.json", {}) or {},
                           live=live, report_info=report_model_info())


@app.get("/reports")
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
def report_file(filename: str):
    # send_from_directory keeps manipulated names inside reports/.
    return send_from_directory(REPORTS_DIR, filename, as_attachment=filename.endswith(".md"))


@app.get("/reports/confusion/<model>.png")
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
            role = "analyst" if email in ANALYST_EMAILS else "citizen"
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
                "SELECT id, password_hash, session_version FROM users WHERE email = ? COLLATE NOCASE",
                (email,)).fetchone()
        # Always verify a hash so response time does not reveal whether the email exists.
        valid = check_password_hash(user["password_hash"] if user else DUMMY_PASSWORD_HASH, password)
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
            started = time.perf_counter()
            result = classify_report(values["description"], values["channel"], values["affected"])
            inference_ms = (time.perf_counter() - started) * 1000
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
                       alternatives_json, needs_review, model_version, inference_ms, duration_seconds)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (g.user["id"], values["occurred_on"], values["department"], values["municipality"],
                     values["channel"], ";".join(values["affected"]),
                     int(values["amount_lost"]) if values["amount_lost"] else None,
                     values["description"], result["category"], result["confidence"],
                     json.dumps(result["alternatives"]), int(result["needs_review"]),
                     result["model_version"], inference_ms, duration))
            logger.info("report=%s category=%s confidence=%.3f inference_ms=%.1f",
                        cursor.lastrowid, result["category"], result["confidence"], inference_ms)
            return redirect(url_for("report_submitted", report_id=cursor.lastrowid))
    return render_template("report_form.html", page_title="New report", values=values,
                           errors=errors, departments=departments(), channels=CHANNELS,
                           affected=AFFECTED, today=date.today().isoformat(),
                           min_date=(date.today() - timedelta(days=365 * 5)).isoformat(),
                           started_at=int(time.time()))


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
                           department_cases=cases)


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
@app.get("/review")
@analyst_required
def review():
    status = request.args.get("status", "open")
    query = "SELECT r.*, u.name AS reporter FROM incident_reports r JOIN users u ON u.id = r.user_id"
    params: tuple = ()
    if status in STATUSES:
        query += " WHERE r.status = ?"
        params = (status,)
    elif status == "open":
        query += " WHERE r.status != 'closed'"
    with connect_db() as connection:
        rows = connection.execute(query + " ORDER BY r.needs_review DESC, r.created_at DESC LIMIT 200",
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
        reports_list.append(item)
    return render_template("review.html", page_title="Review", reports=reports_list, stats=dict(stats),
                           status=status, statuses=STATUSES, model=report_model_info())


@app.post("/review/<int:report_id>")
@analyst_required
def review_update(report_id: int):
    validate_csrf()
    status = request.form.get("status", "")
    confirmed = request.form.get("confirmed_category", "")
    note = request.form.get("analyst_note", "").strip()[:500]
    if status not in STATUSES or (confirmed and confirmed not in CATEGORY_INFO):
        abort(400, description="Choose a valid status and category.")
    if status == "closed" and not confirmed:
        flash("Confirm the category before closing a report.", "error")
        return redirect(url_for("review"))
    with connect_db() as connection:
        updated = connection.execute(
            "UPDATE incident_reports SET status = ?, confirmed_category = ?, analyst_note = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, confirmed or None, note, report_id)).rowcount
    if not updated:
        abort(404)
    flash(f"Report {report_id} updated.", "success")
    return redirect(url_for("review", status=request.args.get("status", "open")))


# --------------------------------------------------------------------------- CLI
@app.cli.command("make-analyst")
@click.argument("email")
def make_analyst(email: str):
    """Give the analyst role to an existing account."""
    ensure_database()
    with connect_db() as connection:
        changed = connection.execute("UPDATE users SET role = 'analyst' WHERE email = ? COLLATE NOCASE",
                                     (email.strip(),)).rowcount
    click.echo(f"{email} is now an analyst." if changed else f"No account found for {email}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
