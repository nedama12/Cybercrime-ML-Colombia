"""Access-control, incident-workflow and report-export integration tests."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import app as web


class RolesIncidentsReportsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-roles-")
        self.original_path = web.USER_DB_PATH
        web.USER_DB_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        web.app.config.update(TESTING=True, SECRET_KEY="roles-test-secret")
        web.ensure_user_database()
        with web.connect_db() as connection:
            for name, email, role in (("Admin", "admin@example.test", "admin"),
                                      ("Analyst", "analyst@example.test", "analyst"),
                                      ("User A", "a@example.test", "user"),
                                      ("User B", "b@example.test", "user")):
                connection.execute(
                    "INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                    (name, email, "test-hash", role))

    def tearDown(self):
        web.USER_DB_PATH = self.original_path
        self.temp_dir.cleanup()

    @staticmethod
    def login_as(user_id):
        client = web.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
        return client

    @staticmethod
    def csrf(client, path):
        response = client.get(path)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if not match:
            raise AssertionError(f"Missing CSRF token at {path}")
        return match.group(1).decode()

    def test_roles_are_enforced_on_server(self):
        anonymous = web.app.test_client()
        self.assertEqual(anonymous.get("/dataset").status_code, 302)
        self.assertEqual(self.login_as(3).get("/dataset").status_code, 403)
        self.assertEqual(self.login_as(2).get("/dataset").status_code, 200)
        self.assertEqual(self.login_as(2).get("/admin/users").status_code, 403)
        self.assertEqual(self.login_as(1).get("/admin/users").status_code, 200)
        self.assertEqual(self.login_as(3).get("/reports/export.csv").status_code, 403)
        self.assertEqual(self.login_as(2).get("/reports/export.csv").status_code, 200)

    def test_user_incident_visibility_and_analyst_review_history(self):
        user_a = self.login_as(3)
        token = self.csrf(user_a, "/incidents")
        created = user_a.post("/incidents", data={
            "csrf_token": token, "category": "Phishing", "occurred_at": "2026-11-14",
            "description": "I received a suspicious link and did not enter any credentials.",
        })
        self.assertEqual(created.status_code, 302)
        self.assertEqual(user_a.get("/incidents").status_code, 200)
        with web.connect_db() as connection:
            incident_id = connection.execute("SELECT id FROM incidents").fetchone()["id"]
        self.assertEqual(user_a.get(f"/incidents/{incident_id}").status_code, 200)
        self.assertEqual(self.login_as(4).get(f"/incidents/{incident_id}").status_code, 404)
        analyst = self.login_as(2)
        self.assertEqual(analyst.get("/incidents").status_code, 200)
        token = self.csrf(analyst, f"/incidents/{incident_id}")
        reviewed = analyst.post(f"/incidents/{incident_id}/review", data={
            "csrf_token": token, "status": "Under Review", "note": "Check sender and preserve message headers."})
        self.assertEqual(reviewed.status_code, 302)
        detail = analyst.get(f"/incidents/{incident_id}")
        self.assertIn(b"Under Review", detail.data)
        self.assertIn(b"preserve message headers", detail.data)
        with web.connect_db() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM incident_updates WHERE incident_id=?", (incident_id,)).fetchone()[0], 2)

    def test_admin_role_updates_and_last_admin_protection(self):
        admin = self.login_as(1)
        token = self.csrf(admin, "/admin/users")
        response = admin.post("/admin/users/3", data={
            "csrf_token": token, "role": "analyst", "is_active": "1"})
        self.assertEqual(response.status_code, 302)
        with web.connect_db() as connection:
            self.assertEqual(connection.execute("SELECT role FROM users WHERE id=3").fetchone()[0], "analyst")
        token = self.csrf(admin, "/admin/users")
        admin.post("/admin/users/1", data={
            "csrf_token": token, "role": "user", "is_active": "1"})
        with web.connect_db() as connection:
            self.assertEqual(connection.execute("SELECT role FROM users WHERE id=1").fetchone()[0], "admin")

    def test_initial_admin_cli_only_promotes_an_existing_account(self):
        runner = web.app.test_cli_runner()
        missing = runner.invoke(args=["promote-admin", "missing@example.test"])
        self.assertNotEqual(missing.exit_code, 0)
        promoted = runner.invoke(args=["promote-admin", "b@example.test"])
        self.assertEqual(promoted.exit_code, 0, promoted.output)
        with web.connect_db() as connection:
            self.assertEqual(connection.execute(
                "SELECT role FROM users WHERE email='b@example.test'").fetchone()[0], "admin")

    def test_invalid_incident_category_and_missing_csrf_are_rejected(self):
        user = self.login_as(3)
        invalid = user.post("/incidents", data={
            "category": "Unknown", "description": "This description is long enough to pass length validation."})
        self.assertEqual(invalid.status_code, 400)
        token = self.csrf(user, "/incidents")
        valid = user.post("/incidents", data={
            "csrf_token": token, "category": "Phishing", "description": "This description is long enough to pass validation."})
        self.assertEqual(valid.status_code, 302)


if __name__ == "__main__":
    unittest.main()
