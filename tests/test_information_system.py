"""Activity 2 tests: roles and permissions, report CRUD, inference history, support requests,
indicators, territorial analysis, operational monitoring and administration."""
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

import app as web

PASSWORD = "SecurePass123"


class InformationSystemTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-is-test-")
        web.USER_DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        web.ANALYST_EMAILS.add("analyst.is@example.test")
        web.ADMIN_EMAILS.add("admin.is@example.test")
        web.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")
        cls.citizen = cls.register("Citizen One", "citizen.is@example.test")
        cls.other = cls.register("Citizen Two", "other.is@example.test")
        cls.analyst = cls.register("Analyst One", "analyst.is@example.test")
        cls.admin = cls.register("Admin One", "admin.is@example.test")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def csrf(client, path="/dashboard"):
        token = re.search(rb'name="csrf_token" value="([^"]+)"', client.get(path).data)
        if not token:
            raise AssertionError(f"No CSRF token in {path}")
        return token.group(1).decode()

    @classmethod
    def register(cls, name, email, extra=None):
        client = web.app.test_client()
        data = {"csrf_token": cls.csrf(client, "/register"), "name": name, "email": email, "password": PASSWORD}
        data.update(extra or {})
        response = client.post("/register", data=data)
        assert response.status_code == 302, response.status_code
        return client

    def db(self, sql, *args):
        with closing(sqlite3.connect(web.USER_DB_PATH)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(sql, args).fetchall()

    def new_report(self, client, **overrides):
        data = {"csrf_token": self.csrf(client, "/report/new"), "occurred_on": date.today().isoformat(),
                "department": "ANTIOQUIA", "municipality": "Medellin", "channel": "sms_whatsapp",
                "affected": ["money", "account"], "amount_lost": "800000", "consent": "yes", "started_at": "0",
                "description": "I received a WhatsApp from my bank with a link, typed my password and money "
                               "left my account"}
        data.update(overrides)
        response = client.post("/report/new", data=data)
        self.assertEqual(response.status_code, 302, response.data[:400])
        return int(re.search(r"/report/(\d+)/", response.headers["Location"]).group(1))

    # ------------------------------------------------------------------ roles
    def test_registration_cannot_grant_privileges(self):
        self.register("Sneaky", "sneaky.is@example.test", {"role": "admin"})
        role = self.db("SELECT role FROM users WHERE email = ?", "sneaky.is@example.test")[0]["role"]
        self.assertEqual(role, "citizen")

    def test_each_role_only_opens_its_modules(self):
        staff_pages = ["/review", "/indicators", "/indicators/reports.csv", "/inferences", "/support/manage"]
        admin_pages = ["/admin/users", "/admin/operations"]
        anonymous = web.app.test_client()
        for path in staff_pages + admin_pages + ["/support", "/territorial-analysis"]:
            self.assertEqual(anonymous.get(path).status_code, 302, path)
        for path in staff_pages + admin_pages:
            self.assertEqual(self.citizen.get(path).status_code, 403, path)
        for path in staff_pages:
            self.assertEqual(self.analyst.get(path).status_code, 200, path)
        for path in admin_pages:
            self.assertEqual(self.analyst.get(path).status_code, 403, path)
        for path in staff_pages + admin_pages:
            self.assertEqual(self.admin.get(path).status_code, 200, path)

    def test_admin_manages_roles_and_deactivation(self):
        client = self.register("Future Analyst", "future.is@example.test")
        user_id = self.db("SELECT id FROM users WHERE email = ?", "future.is@example.test")[0]["id"]
        token = self.csrf(self.admin, "/admin/users")
        self.admin.post(f"/admin/users/{user_id}", data={"csrf_token": token, "role": "analyst", "active": "1"})
        self.assertEqual(self.db("SELECT role FROM users WHERE id = ?", user_id)[0]["role"], "analyst")
        # The role change ends the open session: the user must log in again.
        self.assertEqual(client.get("/review").status_code, 302)
        self.admin.post(f"/admin/users/{user_id}", data={"csrf_token": token, "role": "analyst", "active": "0"})
        login = web.app.test_client()
        response = login.post("/login", data={"csrf_token": self.csrf(login, "/login"),
                                              "email": "future.is@example.test", "password": PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.db("SELECT 1 FROM audit_log WHERE target = ?", "future.is@example.test"))
        # Administrators cannot change their own role.
        admin_id = self.db("SELECT id FROM users WHERE email = ?", "admin.is@example.test")[0]["id"]
        self.admin.post(f"/admin/users/{admin_id}", data={"csrf_token": token, "role": "citizen", "active": "1"})
        self.assertEqual(self.db("SELECT role FROM users WHERE id = ?", admin_id)[0]["role"], "admin")

    # ------------------------------------------------------------------ report CRUD and inference history
    def test_citizen_edits_and_deletes_own_report_while_received(self):
        report_id = self.new_report(self.citizen)
        row = self.db("SELECT * FROM incident_reports WHERE id = ?", report_id)[0]
        self.assertEqual(row["priority"], "medium")
        inference = self.db("SELECT * FROM inferences WHERE report_id = ?", report_id)
        self.assertEqual(len(inference), 1)
        self.assertTrue(inference[0]["model_version"].startswith("logistic_regression@"))
        self.assertIsNotNone(inference[0]["user_id"])

        # Another citizen cannot open, edit or delete it.
        self.assertEqual(self.other.get(f"/report/{report_id}/edit").status_code, 404)
        token = self.csrf(self.other)
        self.assertEqual(self.other.post(f"/report/{report_id}/delete", data={"csrf_token": token}).status_code, 404)

        edit = self.new_report_payload(self.citizen, f"/report/{report_id}/edit",
                                       description="A man called me pretending to be my bank and I transferred "
                                                   "money to his account because he said it was safe")
        self.assertEqual(self.citizen.post(f"/report/{report_id}/edit", data=edit).status_code, 302)
        self.assertEqual(len(self.db("SELECT * FROM inferences WHERE report_id = ?", report_id)), 2)
        actions = [r["action"] for r in self.db("SELECT action FROM report_events WHERE report_id = ?", report_id)]
        self.assertEqual(actions[:3], ["created", "edited", "reclassified"])

        token = self.csrf(self.citizen)
        self.citizen.post(f"/report/{report_id}/delete", data={"csrf_token": token})
        self.assertFalse(self.db("SELECT 1 FROM incident_reports WHERE id = ?", report_id))
        # The inference history is kept for traceability.
        self.assertEqual(len(self.db("SELECT * FROM inferences WHERE report_id IS NULL AND source != 'demo'")) >= 2,
                         True)

    def new_report_payload(self, client, path, **overrides):
        data = {"csrf_token": self.csrf(client, path), "occurred_on": date.today().isoformat(),
                "department": "ANTIOQUIA", "municipality": "Medellin", "channel": "phone_call",
                "affected": ["money"], "amount_lost": "800000", "consent": "yes", "started_at": "0"}
        data.update(overrides)
        return data

    def test_review_locks_report_and_keeps_audit_trail(self):
        report_id = self.new_report(self.citizen)
        token = self.csrf(self.analyst, "/review")
        self.analyst.post(f"/review/{report_id}", data={"csrf_token": token, "status": "closed",
                                                        "confirmed_category": "TRANSFER_FRAUD",
                                                        "analyst_note": "Call your bank."})
        row = self.db("SELECT * FROM incident_reports WHERE id = ?", report_id)[0]
        self.assertEqual(row["status"], "closed")
        self.assertIsNotNone(row["closed_at"])
        # Closed reports cannot be edited or deleted by the citizen.
        self.assertEqual(self.citizen.get(f"/report/{report_id}/edit").status_code, 302)
        self.citizen.post(f"/report/{report_id}/delete", data={"csrf_token": self.csrf(self.citizen)})
        self.assertTrue(self.db("SELECT 1 FROM incident_reports WHERE id = ?", report_id))
        actions = {r["action"] for r in self.db("SELECT action FROM report_events WHERE report_id = ?", report_id)}
        self.assertTrue({"created", "status", "category", "note"} <= actions)
        page = self.citizen.get(f"/report/{report_id}/submitted").get_data(as_text=True)
        self.assertIn("Category confirmed by an analyst", page)
        # Only an administrator can delete it, with a reason.
        self.assertEqual(self.analyst.post(f"/review/{report_id}/delete",
                                           data={"csrf_token": token, "reason": "Duplicate"}).status_code, 403)
        admin_token = self.csrf(self.admin, "/review")
        self.admin.post(f"/review/{report_id}/delete", data={"csrf_token": admin_token, "reason": "Duplicate"})
        self.assertFalse(self.db("SELECT 1 FROM incident_reports WHERE id = ?", report_id))

    def test_disagreement_raises_priority(self):
        report_id = self.new_report(self.citizen, affected=["personal_data"], amount_lost="",
                                    description="Someone published my phone number and address in a Facebook "
                                                "group without my permission")
        self.assertEqual(self.db("SELECT priority FROM incident_reports WHERE id = ?", report_id)[0]["priority"],
                         "normal")
        self.citizen.post(f"/report/{report_id}/feedback", data={"csrf_token": self.csrf(self.citizen),
                                                                 "agrees": "no"})
        self.assertEqual(self.db("SELECT priority FROM incident_reports WHERE id = ?", report_id)[0]["priority"],
                         "high")

    # ------------------------------------------------------------------ support requests
    def test_support_ticket_lifecycle(self):
        token = self.csrf(self.citizen, "/support")
        bad = self.citizen.post("/support", data={"csrf_token": token, "kind": "technical_issue",
                                                  "subject": "Login", "message": "my password: Secret123 fails"})
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(self.db("SELECT 1 FROM support_tickets WHERE subject = 'Login'"))
        self.citizen.post("/support", data={"csrf_token": token, "kind": "technical_issue",
                                            "subject": "Page error", "message": "The report page showed an error."})
        ticket = self.db("SELECT * FROM support_tickets WHERE subject = 'Page error'")[0]
        staff_token = self.csrf(self.analyst, "/support/manage")
        self.analyst.post(f"/support/{ticket['id']}", data={"csrf_token": staff_token, "status": "resolved",
                                                            "staff_response": ""})
        self.assertEqual(self.db("SELECT status FROM support_tickets WHERE id = ?", ticket["id"])[0]["status"], "open")
        self.analyst.post(f"/support/{ticket['id']}", data={"csrf_token": staff_token, "status": "resolved",
                                                            "staff_response": "Fixed, please try again."})
        self.assertIn("Fixed, please try again.", self.citizen.get("/support").get_data(as_text=True))
        self.assertNotIn("Page error", self.other.get("/support").get_data(as_text=True))

    # ------------------------------------------------------------------ indicators, analytics, monitoring
    def test_indicators_and_anonymous_export(self):
        self.new_report(self.other)
        page = self.analyst.get("/indicators?days=30").get_data(as_text=True)
        self.assertIn("Business", page)
        export = self.analyst.get("/indicators/reports.csv")
        self.assertEqual(export.mimetype, "text/csv")
        text = export.get_data(as_text=True)
        self.assertIn("predicted_category", text.splitlines()[0])
        self.assertNotIn("other.is@example.test", text)
        self.assertNotIn("WhatsApp from my bank", text)
        self.assertIn("logistic_regression@", self.analyst.get("/inferences").get_data(as_text=True))

    def test_territorial_analysis_filters(self):
        page = self.citizen.get("/territorial-analysis")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Annual outlook", page.get_data(as_text=True))
        filtered = self.citizen.get("/territorial-analysis?scope=department&department=ANTIOQUIA"
                                    "&category=ELECTRONIC_THEFT&basis=event&year=1900&compare_level=bad")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn("Antioquia", filtered.get_data(as_text=True))

    def test_operations_logging_and_review(self):
        self.citizen.get("/dashboard")
        rows = self.db("SELECT * FROM request_log WHERE endpoint = 'dashboard'")
        self.assertTrue(rows and rows[0]["duration_ms"] >= 0)
        page = self.admin.get("/admin/operations?days=7").get_data(as_text=True)
        self.assertIn("Model registry", page)
        self.assertTrue(self.db("SELECT 1 FROM model_versions WHERE active = 1"))
        token = self.csrf(self.admin, "/admin/operations")
        self.admin.post("/admin/operations?days=7", data={"csrf_token": token,
                                                          "findings": "No server errors in the test session.",
                                                          "actions": "Keep weekly review."})
        review = self.db("SELECT * FROM operational_reviews")
        self.assertEqual(len(review), 1)
        self.assertIn("requests", review[0]["metrics_json"])
        health = web.app.test_client().get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["database"], "ok")

    def test_public_documentation_pages(self):
        anonymous = web.app.test_client()
        for path in ("/", "/system", "/help"):
            self.assertEqual(anonymous.get(path).status_code, 200, path)

    def test_account_deletion_requires_password(self):
        client = self.register("Leaving User", "leaving.is@example.test")
        token = self.csrf(client, "/account")
        client.post("/account/delete", data={"csrf_token": token, "password": "wrong-password1"})
        self.assertTrue(self.db("SELECT 1 FROM users WHERE email = ?", "leaving.is@example.test"))
        client.post("/account/delete", data={"csrf_token": token, "password": PASSWORD})
        self.assertFalse(self.db("SELECT 1 FROM users WHERE email = ?", "leaving.is@example.test"))


if __name__ == "__main__":
    unittest.main()
