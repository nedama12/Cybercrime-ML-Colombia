"""Checks for the assistant's rule-based guidance and public Flask flow."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import app as web
from src.cybersecurity_guidance import assess_situation


class CybersecurityAssistantTest(unittest.TestCase):
    def test_phishing_password_exposure_gets_post_incident_steps(self):
        result = assess_situation(
            "phishing", "I entered my password on a suspicious link yesterday", "post")
        self.assertEqual(result["state"], "POST-INCIDENT")
        self.assertEqual(result["urgency"], "High")
        self.assertTrue(any("Change the exposed password" in step[0]
                            for step in result["immediate"]))
        self.assertIn("impersonating a trusted source", result["what_it_means"])
        self.assertTrue(all("why" in step and "outcome" in step
                            for section in result["action_sections"]
                            for step in section["steps"]))

    def test_transfer_fraud_prioritizes_bank_contact(self):
        result = assess_situation("fraud", "A transfer was made from my bank account", "active")
        self.assertEqual(result["urgency"], "Critical")
        self.assertIn("Contact your bank immediately", result["immediate"][0][0])

    def test_exposure_signals_change_priority_and_response_steps(self):
        clicked = assess_situation("phishing", "I opened a link", "post", ["clicked_link"])
        credential = assess_situation("phishing", "A suspicious message", "post",
                                      ["entered_password"])
        self.assertEqual(clicked["urgency"], "High")
        self.assertTrue(any("Close the page" in step[0] for step in clicked["immediate"]))
        self.assertTrue(any("Change the exposed password" in step[0]
                            for step in credential["immediate"]))

    def test_opened_file_adds_device_containment_step(self):
        result = assess_situation("malware", "I opened an attachment", "post", ["opened_file"])
        self.assertTrue(any("Do not open the file again" in step[0]
                            for step in result["immediate"]))

    def test_vague_description_requests_clarification(self):
        self.assertTrue(assess_situation("other", "help", "prevention")["needs_clarification"])

    def test_main_public_routes_and_assistant_post(self):
        original_db = web.USER_DB_PATH
        with tempfile.TemporaryDirectory(prefix="assistant-route-") as directory:
            web.USER_DB_PATH = Path(directory) / "users.sqlite"
            web.app.config.update(TESTING=True, SECRET_KEY="assistant-test-secret")
            try:
                client = web.app.test_client()
                web.ensure_user_database()
                with web.connect_db() as connection:
                    connection.execute(
                        "INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                        ("Analyst", "assistant-analyst@example.test", "test-only", "analyst"),
                    )
                with client.session_transaction() as session:
                    session["user_id"] = 1
                for route in ("/", "/dataset", "/territorial-analysis", "/assistant",
                              "/preprocessing", "/models", "/evaluation", "/reports"):
                    with self.subTest(route=route):
                        self.assertEqual(client.get(route).status_code, 200)
                form = client.get("/assistant")
                token = re.search(rb'name="csrf_token" value="([^"]+)"', form.data).group(1).decode()
                response = client.post("/assistant", data={
                    "csrf_token": token, "problem": "fraud", "status": "active",
                    "description": "A transfer was made from my bank account",
                    "exposure": ["sent_money"],
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Contact your bank immediately", response.data)
                self.assertIn(b"Why this priority:", response.data)
            finally:
                web.USER_DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
