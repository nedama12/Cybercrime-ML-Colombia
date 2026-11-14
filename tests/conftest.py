"""Shared fixtures. Tests use an in-memory SQLite database and a tiny model trained on
synthetic data, so they run without the real dataset or the production model."""
import json
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from flask import g
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from cyberapp import create_app
from cyberapp.config import TestConfig
from cyberapp.extensions import db
from cyberapp.ml.features import COMPUTABLE_FEATURES
from cyberapp.models import Role, User

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "Secret123"


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    """A fitted Pipeline that follows the model contract (models/README.md)."""
    folder = tmp_path_factory.mktemp("model")
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((300, len(COMPUTABLE_FEATURES))) * 50, columns=COMPUTABLE_FEATURES)
    y = (X["URLLength"] > 25).astype(int)  # longer URLs -> "phishing" in this toy model
    pipe = Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression())]).fit(X, y)
    joblib.dump(pipe, folder / "phishing_model.joblib")
    (folder / "model_metadata.json").write_text(json.dumps({
        "model_name": "test-model", "version": "9.9.9", "algorithm": "LogisticRegression",
        "features": COMPUTABLE_FEATURES, "threshold": 0.5, "positive_class": 1,
        "metrics": {"test": {"accuracy": 0.9, "precision": 0.9, "recall": 0.9, "f1": 0.9}},
    }))
    for name in ("reference_stats.json", "tld_legitimate_prob.json"):
        if (ROOT / "models" / name).exists():
            shutil.copy(ROOT / "models" / name, folder / name)
    return folder


@pytest.fixture()
def app(model_dir):
    class Config(TestConfig):
        MODEL_DIR = model_dir

    app = create_app(Config)

    # The fixture keeps an application context open so tests can query the database. Requests
    # then reuse that context, so Flask-Login's cached user (g._login_user) must be cleared after
    # each request; otherwise a client would act as the user of the previous request.
    @app.teardown_request
    def _forget_user(exc):
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        for username, role in (("admin", Role.ADMIN), ("analyst", Role.ANALYST),
                               ("reporter", Role.REPORTER), ("other", Role.REPORTER)):
            user = User(username=username, email=f"{username}@example.com", role=role)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def app_without_model(tmp_path):
    class Config(TestConfig):
        MODEL_DIR = tmp_path

    app = create_app(Config)

    @app.teardown_request
    def _forget_user(exc):
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        user = User(username="analyst", email="analyst@example.com", role=Role.ANALYST)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def login(app):
    def _login(username):
        client = app.test_client()
        response = client.post("/auth/login", data={"username": username, "password": PASSWORD})
        assert response.status_code == 302, f"login failed for {username}"
        return client
    return _login


@pytest.fixture()
def reported_case(login):
    """A case reported by 'reporter', returned as (case_id, reporter_client)."""
    client = login("reporter")
    response = client.post("/cases/new", data={"url": "https://secure-login.example.xyz/verify?id=12345",
                                               "channel": "email", "description": "Fake bank"})
    case_id = int(response.headers["Location"].rsplit("/", 1)[-1])
    return case_id, client
