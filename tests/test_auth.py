"""Authentication tests: hashing, password rules, redirects, sessions and headers."""
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from werkzeug.security import generate_password_hash

import app as web


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-auth-")
        cls.original_db = web.USER_DB_PATH
        web.USER_DB_PATH = Path(cls.temp_dir.name) / "auth.sqlite3"
        web.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")

    @classmethod
    def tearDownClass(cls):
        web.USER_DB_PATH = cls.original_db
        cls.temp_dir.cleanup()

    @staticmethod
    def csrf(client, path):
        token = re.search(rb'name="csrf_token" value="([^"]+)"', client.get(path).data)
        return token.group(1).decode()

    def register(self, client, email, password="Blue7Harbor", name="Test User", next_path=""):
        url = "/register" + (f"?next={next_path}" if next_path else "")
        return client.post(url, data={"csrf_token": self.csrf(client, "/register"), "name": name,
                                      "email": email, "password": password})

    def login(self, client, email, password, next_path=""):
        url = "/login" + (f"?next={next_path}" if next_path else "")
        return client.post(url, data={"csrf_token": self.csrf(client, "/login"),
                                      "email": email, "password": password})

    def stored_hash(self, email):
        with closing(sqlite3.connect(web.USER_DB_PATH)) as connection:
            return connection.execute("SELECT password_hash FROM users WHERE email = ?",
                                      (email,)).fetchone()[0]

    def test_password_is_stored_as_scrypt_hash(self):
        client = web.app.test_client()
        self.assertEqual(self.register(client, "hash@example.test").status_code, 302)
        stored = self.stored_hash("hash@example.test")
        self.assertTrue(stored.startswith("scrypt:"))
        self.assertNotIn("Blue7Harbor", stored)

    def test_weak_passwords_are_rejected(self):
        cases = [("short1", b"at least 8"), ("onlyletters", b"one letter and one number"),
                 ("12345678", b"one letter and one number"), ("password123", b"too common"),
                 ("weakuser2026", b"must not contain your email"), ("TestUser99", b"must not contain your email")]
        for password, message in cases:
            client = web.app.test_client()
            response = self.register(client, "weakuser@example.test", password)
            self.assertEqual(response.status_code, 400, password)
            self.assertIn(message, response.data, password)

    def test_report_requires_account_and_returns_to_form(self):
        client = web.app.test_client()
        response = client.get("/report/new")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/report/new", response.headers["Location"])
        login_page = client.get("/login?next=/report/new")
        self.assertIn(b"One step before your report", login_page.data)
        registered = self.register(client, "reporter@example.test", next_path="/report/new")
        self.assertEqual(registered.headers["Location"], "/report/new")
        self.assertEqual(client.get("/report/new").status_code, 200)

    def test_open_redirects_are_blocked(self):
        client = web.app.test_client()
        self.register(client, "redirect@example.test")
        client.post("/logout", data={"csrf_token": self.csrf(client, "/dashboard")})
        for target in ("//evil.example", "/\\evil.example", "https://evil.example/x", "javascript:alert(1)"):
            response = self.login(client, "redirect@example.test", "Blue7Harbor", next_path=target)
            self.assertEqual(response.headers["Location"], "/dashboard", target)
            client.post("/logout", data={"csrf_token": self.csrf(client, "/dashboard")})

    def test_unknown_email_and_wrong_password_look_the_same(self):
        client = web.app.test_client()
        self.register(client, "same@example.test")
        client.post("/logout", data={"csrf_token": self.csrf(client, "/dashboard")})
        unknown = self.login(client, "nobody@example.test", "Blue7Harbor")
        wrong = self.login(client, "same@example.test", "Wrong7Harbor")
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertIn(b"Incorrect email or password", unknown.data)
        self.assertIn(b"Incorrect email or password", wrong.data)

    def test_password_change_signs_out_other_devices(self):
        phone, laptop = web.app.test_client(), web.app.test_client()
        self.register(phone, "devices@example.test")
        self.login(laptop, "devices@example.test", "Blue7Harbor")
        self.assertEqual(laptop.get("/dashboard").status_code, 200)
        changed = phone.post("/account", data={"csrf_token": self.csrf(phone, "/account"),
                                               "current_password": "Blue7Harbor",
                                               "new_password": "Green8Valley"})
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(phone.get("/dashboard").status_code, 200)
        self.assertEqual(laptop.get("/dashboard").status_code, 302)
        self.assertEqual(self.login(laptop, "devices@example.test", "Green8Valley").status_code, 302)

    def test_legacy_hash_is_upgraded_on_login(self):
        web.ensure_database()
        with closing(sqlite3.connect(web.USER_DB_PATH)) as connection, connection:
            connection.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                               ("Legacy", "legacy@example.test",
                                generate_password_hash("Old5Garden", method="pbkdf2:sha256")))
        client = web.app.test_client()
        self.assertEqual(self.login(client, "legacy@example.test", "Old5Garden").status_code, 302)
        self.assertTrue(self.stored_hash("legacy@example.test").startswith("scrypt:"))

    def test_session_cookie_and_security_headers(self):
        client = web.app.test_client()
        response = self.register(client, "headers@example.test")
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        private = client.get("/dashboard")
        self.assertEqual(private.headers["Cache-Control"], "no-store")
        self.assertEqual(private.headers["X-Frame-Options"], "DENY")
        self.assertEqual(private.headers["X-Content-Type-Options"], "nosniff")

    def test_lockout_is_shared_between_workers(self):
        client = web.app.test_client()
        self.register(client, "lock@example.test")
        client.post("/logout", data={"csrf_token": self.csrf(client, "/dashboard")})
        for _ in range(5):
            self.login(client, "lock@example.test", "Wrong7Harbor")
        # A brand-new client (like another gunicorn worker) reads the same database counter.
        other = web.app.test_client()
        blocked = self.login(other, "lock@example.test", "Blue7Harbor")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)


if __name__ == "__main__":
    unittest.main()
