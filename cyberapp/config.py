"""Application settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _database_url():
    """SQLite file for local work; DATABASE_URL (PostgreSQL) in production."""
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'instance' / 'cybercrime.db'}"
    # Render provides postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg 3 driver name.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return url.replace(prefix, "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Session cookies: not readable from JavaScript, sent only on same-site navigation.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True

    # Project folders reused by the documentation pages.
    FIGURES_DIR = BASE_DIR / "analysis" / "figures"
    DATA_DIR = BASE_DIR / "data" / "processed"

    # Folder with the model artifacts delivered by Model Engineering (see models/README.md).
    MODEL_DIR = Path(os.environ.get("MODEL_DIR") or BASE_DIR / "models")


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
