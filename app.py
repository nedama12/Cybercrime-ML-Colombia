"""Plataforma Flask para explorar el dataset y demostrar los modelos ML."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import secrets
import sqlite3
import hmac
import time
from collections import defaultdict, deque
from functools import lru_cache
from functools import wraps
from pathlib import Path
from datetime import timedelta

import pandas as pd
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from src.predict import MODEL_PATH, predict_incident

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
_login_failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_login_blocked_until: dict[tuple[str, str], float] = {}
logger = logging.getLogger(__name__)


def load_secret_key() -> str:
    configured = os.environ.get("FLASK_SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("FLASK_SECRET_KEY debe tener al menos 32 caracteres.")
        return configured
    if os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("FLASK_SECRET_KEY es obligatoria en producción.")
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


def save_prediction(user_id: int, incident: dict, result: dict) -> int:
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
        row = connection.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        session.clear()
        return None
    return str(row["name"] or row["email"])


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
    logger.exception("Error de base de datos SQLite", exc_info=error)
    return "No fue posible completar la operación. Inténtalo de nuevo más tarde.", 503


@app.before_request
def prepare_user_database():
    ensure_user_database()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Inicia sesión para realizar una predicción.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def validate_csrf() -> None:
    expected = session.get("_csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="Formulario vencido o token de seguridad inválido. Recarga la página.")


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
        ("decision_tree", "Decision Tree", "Construye reglas jerárquicas dividiendo los datos por sus atributos."),
        ("random_forest", "Random Forest", "Combina árboles entrenados sobre muestras y subconjuntos de variables."),
        ("logistic_regression", "Logistic Regression", "Estima probabilidades por clase mediante una función logística multiclase."),
    ]:
        report = read_json(CLASS_REPORT_DIR / f"{key}.json", {}) or {}
        metric = next((row for row in get_metrics() if row.get("model") == key), {})
        summaries.append({"key": key, "title": title, "description": description,
                          "best": key == best, "metrics": metric, "report": report,
                          "parameters": metadata.get("parameters", {}) if key == best else {}})
    return summaries


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
            "current_user": current_user_email(),
            "csrf_token": session.setdefault("_csrf_token", secrets.token_urlsafe(32))}


@app.get("/")
def home():
    return render_template("index.html", page_title="Inicio")


@app.get("/dashboard")
@login_required
def dashboard():
    data = dataset_context()
    info = get_info()
    with connect_db() as connection:
        prediction_count = connection.execute(
            "SELECT COUNT(*) FROM predictions WHERE user_id = ?", (session["user_id"],)
        ).fetchone()[0]
    return render_template("dashboard.html", page_title="Panel", data=data, info=info,
                           metrics=get_metrics(), prediction_count=prediction_count)


@app.get("/dataset")
def dataset():
    data = dataset_context()
    return render_template("dataset.html", page_title="Dataset", data=data)


@app.get("/preprocessing")
def preprocessing():
    info = get_info()
    data = dataset_context()
    return render_template("preprocessing.html", page_title="Preparación", info=info, data=data)


@app.get("/models")
def models():
    return render_template("models.html", page_title="Modelos", models=get_model_summaries(), info=get_info())


@app.get("/evaluation")
def evaluation():
    return render_template("evaluation.html", page_title="Evaluación", metrics=get_metrics(),
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
            flash("Ingresa un nombre de hasta 100 caracteres.", "error")
        elif len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Ingresa un correo electrónico válido.", "error")
        elif len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
        elif len(password) > 256:
            flash("La contraseña es demasiado larga.", "error")
        else:
            try:
                with connect_db() as connection:
                    cursor = connection.execute(
                        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                        (name, email, generate_password_hash(password)))
                session.clear()
                session["user_id"] = cursor.lastrowid
                session.permanent = True
                flash("Cuenta creada. Ya puedes hacer una predicción.", "success")
                return redirect(url_for("prediction"))
            except sqlite3.IntegrityError:
                flash("Ya existe una cuenta con ese correo.", "error")
    return render_template("register.html", page_title="Crear cuenta")


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
            response = render_template("login.html", page_title="Iniciar sesión",
                                       retry_after=retry_after)
            return response, 429, {"Retry-After": str(retry_after)}
        with connect_db() as connection:
            user = connection.execute(
                "SELECT id, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
                (email,)).fetchone()
        _record_login_failure(key)
        if user and check_password_hash(user["password_hash"], password):
            _login_failures.pop(key, None)
            _login_blocked_until.pop(key, None)
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            flash("Sesión iniciada.", "success")
            destination = request.args.get("next", "")
            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)
            return redirect(url_for("prediction"))
        flash("Correo o contraseña incorrectos.", "error")
    return render_template("login.html", page_title="Iniciar sesión")


@app.post("/logout")
def logout():
    validate_csrf()
    session.clear()
    flash("Sesión cerrada.", "success")
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
        entries.append({"id": row["id"], "incident": json.loads(row["incident_json"]),
                        "category": row["category"],
                        "probabilities": sorted(
                            [{"name": name, "value": value} for name, value in probabilities.items()],
                            key=lambda item: item["value"], reverse=True),
                        "created_at": row["created_at"]})
    return render_template("history.html", page_title="Mi historial", predictions=entries)


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
    fields = form_fields()
    result = None
    form_values = request.form.to_dict() if request.method == "POST" else {}
    error = None
    if request.method == "POST":
        validate_csrf()
        incident = {}
        try:
            allowed_fields = {field["name"] for field in fields}
            unexpected_fields = set(request.form) - allowed_fields - {"csrf_token"}
            if unexpected_fields:
                raise ValueError("El formulario contiene campos no permitidos.")
            for field in fields:
                name = field["name"]
                raw = request.form.get(name, "").strip()
                if not raw:
                    raise ValueError(f"El campo {name} es obligatorio.")
                if field["numeric"]:
                    try:
                        incident[name] = int(raw)
                    except ValueError as exc:
                        raise ValueError(f"El campo {name} debe ser un número entero.") from exc
                    if field["minimum"] is not None and not field["minimum"] <= incident[name] <= field["maximum"]:
                        raise ValueError(f"El campo {name} debe estar entre {field['minimum']} y {field['maximum']}.")
                else:
                    if raw not in field["options"]:
                        raise ValueError(f"Selecciona una opción válida para {name}.")
                    incident[name] = raw
            result = predict_incident(incident)
            result["record_id"] = save_prediction(session["user_id"], incident, result)
        except (ValueError, OSError, RuntimeError) as exc:
            error = str(exc)
        except sqlite3.Error:
            result = None
            error = "La predicción se generó, pero no se pudo guardar en tu historial. Inténtalo de nuevo."
    return render_template("prediction.html", page_title="Predicción", fields=fields,
                           result=result, error=error, form_values=form_values, info=get_info())


@app.get("/reports")
def reports():
    info = get_info()
    data = dataset_context()
    return render_template("reports.html", page_title="Informes", info=info, data=data,
                           metrics=get_metrics())


@app.get("/reports/files/<path:filename>")
def report_file(filename: str):
    # send_from_directory evita que nombres manipulados salgan de reports/.
    return send_from_directory(REPORTS_DIR, filename, as_attachment=filename.endswith(".md"))


@app.get("/reports/confusion/<model>.png")
def confusion_image(model: str):
    if model not in {"decision_tree", "random_forest", "logistic_regression"}:
        abort(404)
    return send_from_directory(CONFUSION_DIR, f"{model}.png")


@app.get("/reports/model-comparison.png")
def comparison_image():
    return send_from_directory(REPORTS_DIR, "model_comparison.png")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
