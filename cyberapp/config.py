"""Application settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # Session cookies: not readable from JavaScript, sent only on same-site navigation.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    # Project folders reused by the documentation pages.
    FIGURES_DIR = BASE_DIR / "analysis" / "figures"
    DATA_DIR = BASE_DIR / "data" / "processed"


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
