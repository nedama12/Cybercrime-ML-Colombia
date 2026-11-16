"""The six CRISP-ML phase pages, the public model demo and the monitoring evidence."""
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import app as web

PHASES = {"/business": b"Business and data", "/dataset": b"Data <span>engineering",
          "/models": b"Model <span>engineering", "/evaluation": b"Model <span>evaluation",
          "/deployment": b"Model <span>deployment", "/monitoring": b"Monitoring and"}


class PhasePagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-phases-")
        cls.original_db = web.USER_DB_PATH
        web.USER_DB_PATH = Path(cls.temp_dir.name) / "phases.sqlite3"
        web.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")

    @classmethod
    def tearDownClass(cls):
        web.USER_DB_PATH = cls.original_db
        cls.temp_dir.cleanup()

    def test_every_phase_page_renders_with_navigation(self):
        client = web.app.test_client()
        for path, heading in PHASES.items():
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(heading, response.data, path)
            for other in PHASES:
                self.assertIn(f'href="{other}"'.encode(), response.data, f"{other} missing in nav of {path}")

    def test_phase_content_is_traceable_to_artifacts(self):
        client = web.app.test_client()
        info = web.report_model_info()
        models = client.get("/models").data
        self.assertIn(b"Experiment log", models)
        self.assertIn(b"StratifiedGroupKFold", models)
        evaluation = client.get("/evaluation").data
        self.assertIn(f"{info['metrics']['cv_f1_macro_mean']:.3f}".encode(), evaluation)
        self.assertIn(b"never used for tuning or selection", evaluation)
        self.assertIn(b"Before and after".lower(), client.get("/dataset").data.lower())
        self.assertIn(b"SIMULATED OPERATIONAL DATA", client.get("/monitoring").data)

    def test_public_demo_classifies_without_storing(self):
        client = web.app.test_client()
        token = re.search(rb'name="csrf_token" value="([^"]+)"', client.get("/deployment").data).group(1)
        response = client.post("/deployment", data={
            "csrf_token": token.decode(), "channel": "social_media", "affected": ["account"],
            "description": "someone logged into my Instagram account and changed the password"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unauthorized account access", response.data)
        with closing(sqlite3.connect(web.USER_DB_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM incident_reports").fetchone()[0], 0)

    def test_demo_rejects_short_text(self):
        client = web.app.test_client()
        token = re.search(rb'name="csrf_token" value="([^"]+)"', client.get("/deployment").data).group(1)
        response = client.post("/deployment", data={"csrf_token": token.decode(), "channel": "email",
                                                     "description": "hi"})
        self.assertIn(b"at least 15 characters", response.data)


if __name__ == "__main__":
    unittest.main()
