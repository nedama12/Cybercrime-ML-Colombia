"""Integration tests: accounts, incident reports, privacy, analyst review and migration."""
import re
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from werkzeug.security import check_password_hash

import app as web
from src.report_model import classify_report


class ReportFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-test-")
        web.USER_DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        web.ANALYST_EMAILS.add("analyst@example.test")
        web.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def csrf(client, path):
        response = client.get(path)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if not token:
            raise AssertionError(f"No CSRF token found in {path}")
        return token.group(1).decode()

    def register(self, name, email, password="SecurePass123"):
        client = web.app.test_client()
        token = self.csrf(client, "/register")
        response = client.post("/register", data={"csrf_token": token, "name": name,
                                                  "email": email, "password": password})
        self.assertEqual(response.status_code, 302)
        return client

    def report_payload(self, client, **overrides):
        payload = {"csrf_token": self.csrf(client, "/report/new"),
                   "occurred_on": date.today().isoformat(), "department": "ANTIOQUIA",
                   "municipality": "Medellin", "channel": "sms_whatsapp", "affected": ["money", "account"],
                   "amount_lost": "500000", "consent": "yes", "started_at": "0",
                   "description": "I received a text message from my bank with a link, typed my password "
                                  "and then money was taken from my account"}
        payload.update(overrides)
        return payload

    def test_private_pages_require_login(self):
        anonymous = web.app.test_client()
        for path in ("/dashboard", "/my-reports", "/report/new", "/review"):
            self.assertEqual(anonymous.get(path).status_code, 302, path)
        self.assertEqual(anonymous.get("/report").status_code, 200)
        self.assertEqual(anonymous.get("/history").status_code, 301)

    def test_public_pages_are_in_english(self):
        client = web.app.test_client()
        for path in ("/", "/business", "/dataset", "/models", "/evaluation", "/deployment", "/monitoring", "/reports", "/report",
                     "/login", "/register"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            for spanish in (b"Iniciar sesi", b"Crear cuenta", b"Predicci", b"Evaluaci", b"Preparaci"):
                self.assertNotIn(spanish, response.data, f"{spanish!r} in {path}")

    def test_report_flow_feedback_and_isolation(self):
        user_a = self.register("Person A", "person-a@example.test")
        connection = sqlite3.connect(web.USER_DB_PATH)
        try:
            row = connection.execute("SELECT name, password_hash, role FROM users WHERE email = ?",
                                     ("person-a@example.test",)).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], "Person A")
        self.assertTrue(check_password_hash(row[1], "SecurePass123"))
        self.assertEqual(row[2], "citizen")

        sent = user_a.post("/report/new", data=self.report_payload(user_a))
        self.assertEqual(sent.status_code, 302)
        page = user_a.get(sent.headers["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Your report counts", page.data)
        self.assertIn(b"Make it official", page.data)
        self.assertIn(b"CC-", page.data)

        report_id = int(re.search(r"/report/(\d+)/", sent.headers["Location"]).group(1))
        token = self.csrf(user_a, f"/report/{report_id}/submitted")
        self.assertEqual(user_a.post(f"/report/{report_id}/feedback",
                                     data={"csrf_token": token, "agrees": "yes"}).status_code, 302)
        self.assertIn(b"You confirmed this category", user_a.get(f"/report/{report_id}/submitted").data)

        user_b = self.register("Person B", "person-b@example.test")
        self.assertEqual(user_b.get(f"/report/{report_id}/submitted").status_code, 404)
        self.assertIn(b"You have not sent any report", user_b.get("/my-reports").data)
        self.assertEqual(user_b.get("/review").status_code, 404)

    def test_invalid_reports_are_rejected(self):
        client = self.register("Person C", "person-c@example.test")
        cases = [({"department": "ATLANTIS"}, b"Choose the department"),
                 ({"channel": "pigeon"}, b"how it started"),
                 ({"affected": []}, b"at least one thing"),
                 ({"description": "short"}, b"15 to 600 characters"),
                 ({"consent": ""}, b"authorisation"),
                 ({"occurred_on": "2999-01-01"}, b"within the last five years"),
                 ({"amount_lost": "abc"}, b"numbers only"),
                 ({"user_id": "1"}, b"not allowed")]
        for override, message in cases:
            response = client.post("/report/new", data=self.report_payload(client, **override))
            self.assertEqual(response.status_code, 200, override)
            self.assertIn(message, response.data, override)
        bad_token = self.report_payload(client, csrf_token="invalid")
        self.assertEqual(client.post("/report/new", data=bad_token).status_code, 400)

    def test_analyst_review_closes_report(self):
        citizen = self.register("Person D", "person-d@example.test")
        sent = citizen.post("/report/new", data=self.report_payload(
            citizen, channel="social_media", affected=["account"],
            description="Someone logged into my Instagram account and changed the password"))
        report_id = int(re.search(r"/report/(\d+)/", sent.headers["Location"]).group(1))
        analyst = self.register("Analyst", "analyst@example.test")
        self.assertIn(b"Review", analyst.get("/review").data)
        token = self.csrf(analyst, "/review")
        closed_without_category = analyst.post(f"/review/{report_id}", data={
            "csrf_token": token, "status": "closed", "confirmed_category": ""})
        self.assertEqual(closed_without_category.status_code, 302)
        analyst.post(f"/review/{report_id}", data={
            "csrf_token": token, "status": "closed", "confirmed_category": "ABUSIVE_ACCESS",
            "analyst_note": "Recover the account with the platform."})
        page = citizen.get("/my-reports")
        self.assertIn(b"Closed", page.data)
        self.assertIn(b"Recover the account", page.data)

    def test_login_throttling(self):
        client = self.register("Person E", "person-e@example.test")
        token = self.csrf(client, "/dashboard")
        client.post("/logout", data={"csrf_token": token})
        for _ in range(5):
            token = self.csrf(client, "/login")
            response = client.post("/login", data={"csrf_token": token, "email": "person-e@example.test",
                                                   "password": "wrong-password"})
        token = self.csrf(client, "/login")
        blocked = client.post("/login", data={"csrf_token": token, "email": "person-e@example.test",
                                              "password": "SecurePass123"})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn(b"Too many recent attempts", blocked.data)

    def test_classifier_gives_confident_answers(self):
        examples = [
            ("money disappeared from my savings account, purchases I did not make", "unknown", ["money"],
             "ELECTRONIC_THEFT"),
            ("I paid a seller on marketplace and he never sent the product", "social_media", ["money"],
             "TRANSFER_FRAUD"),
            ("my company website is down because of a flood of traffic", "website_app",
             ["business_system"], "SYSTEM_ATTACK"),
        ]
        for text, channel, affected, expected in examples:
            result = classify_report(text, channel, affected)
            self.assertEqual(result["category"], expected, text)
            self.assertGreaterEqual(result["confidence"], 0.5, text)

    def test_additive_migration_preserves_existing_records(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO users(email,password_hash) VALUES('old@example.test','existing-hash');
            """)
            connection.commit()
        finally:
            connection.close()
        original_path = web.USER_DB_PATH
        try:
            web.USER_DB_PATH = legacy_path
            web.ensure_database()
        finally:
            web.USER_DB_PATH = original_path
        connection = sqlite3.connect(legacy_path)
        try:
            self.assertEqual(connection.execute("SELECT name, email, password_hash, role FROM users").fetchone(),
                             ("", "old@example.test", "existing-hash", "citizen"))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
