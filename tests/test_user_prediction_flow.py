"""Prueba de integración local: cuentas, predicción persistida y privacidad."""
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from werkzeug.security import check_password_hash

import app as web


class UserPredictionFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="cybercrime-auth-test-")
        web.USER_DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        web.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def csrf(client, path):
        response = client.get(path)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if not token:
            raise AssertionError(f"No se encontró token CSRF en {path}")
        return token.group(1).decode()

    def test_registration_prediction_history_and_isolation(self):
        anonymous = web.app.test_client()
        self.assertEqual(anonymous.get("/dashboard").status_code, 302)
        self.assertEqual(anonymous.get("/history").status_code, 302)
        self.assertEqual(anonymous.get("/prediction").status_code, 302)

        user_a = web.app.test_client()
        token = self.csrf(user_a, "/register")
        registered = user_a.post("/register", data={
            "csrf_token": token, "name": "Persona A", "email": "persona-a@example.test", "password": "ClaveSeguraA123"
        })
        self.assertEqual(registered.status_code, 302)
        self.assertEqual(user_a.get("/dashboard").status_code, 200)

        duplicate_client = web.app.test_client()
        duplicate_token = self.csrf(duplicate_client, "/register")
        duplicate = duplicate_client.post("/register", data={
            "csrf_token": duplicate_token, "name": "Duplicada",
            "email": "PERSONA-A@example.test", "password": "ClaveSeguraA123"
        })
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"Ya existe una cuenta", duplicate.data)

        connection = sqlite3.connect(web.USER_DB_PATH)
        try:
            user_row = connection.execute(
                "SELECT id, name, password_hash FROM users WHERE email = ?",
                ("persona-a@example.test",)).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(user_row)
        self.assertEqual(user_row[1], "Persona A")
        self.assertTrue(check_password_hash(user_row[2], "ClaveSeguraA123"))

        token = self.csrf(user_a, "/prediction")
        row = pd.read_csv(web.DATA_PATH, nrows=1).iloc[0]
        payload = {name: str(row[name]) for name in web.get_info()["features"]}
        payload["csrf_token"] = token
        prediction = user_a.post("/prediction", data=payload)
        self.assertEqual(prediction.status_code, 200)
        self.assertIn(b"guardada en tu cuenta", prediction.data)
        self.assertEqual(user_a.get("/history").status_code, 200)
        self.assertIn(b"Predicci\xc3\xb3n #1", user_a.get("/history").data)

        connection = sqlite3.connect(web.USER_DB_PATH)
        try:
            record = connection.execute(
                "SELECT user_id, category FROM predictions WHERE id = 1").fetchone()
        finally:
            connection.close()
        self.assertEqual(record[0], user_row[0])
        self.assertTrue(record[1])

        # Server-side checks reject unknown categories and values outside observed ranges.
        token = self.csrf(user_a, "/prediction")
        invalid_category = {**payload, "csrf_token": token, "departamento_hecho": "__INVALIDO__"}
        rejected_category = user_a.post("/prediction", data=invalid_category)
        self.assertEqual(rejected_category.status_code, 200)
        self.assertIn("opción válida".encode("utf-8"), rejected_category.data)
        token = self.csrf(user_a, "/prediction")
        invalid_numeric = {**payload, "csrf_token": token, "ano_hechos": "999999"}
        rejected_numeric = user_a.post("/prediction", data=invalid_numeric)
        self.assertEqual(rejected_numeric.status_code, 200)
        self.assertIn("debe estar entre".encode("utf-8"), rejected_numeric.data)
        token = self.csrf(user_a, "/prediction")
        unexpected_field = {**payload, "csrf_token": token, "user_id": "2"}
        rejected_extra = user_a.post("/prediction", data=unexpected_field)
        self.assertEqual(rejected_extra.status_code, 200)
        self.assertIn("campos no permitidos".encode("utf-8"), rejected_extra.data)

        user_b = web.app.test_client()
        token = self.csrf(user_b, "/register")
        response = user_b.post("/register", data={
            "csrf_token": token, "name": "Persona B", "email": "persona-b@example.test", "password": "ClaveSeguraB123"
        })
        self.assertEqual(response.status_code, 302)
        history_b = user_b.get("/history")
        self.assertEqual(history_b.status_code, 200)
        self.assertIn(b"Tu historial est\xc3\xa1 vac\xc3\xado", history_b.data)
        self.assertNotIn(b"Predicci\xc3\xb3n #1", history_b.data)

        token = self.csrf(user_b, "/prediction")
        bad_payload = {**payload, "csrf_token": "invalid"}
        self.assertEqual(user_b.post("/prediction", data=bad_payload).status_code, 400)

        logout_token = self.csrf(user_b, "/history")
        self.assertEqual(user_b.post("/logout", data={"csrf_token": logout_token}).status_code, 302)
        self.assertEqual(user_b.get("/dashboard").status_code, 302)

        login_token = self.csrf(user_b, "/login")
        rejected = user_b.post("/login", data={
            "csrf_token": login_token, "email": "persona-b@example.test", "password": "incorrecta"
        })
        self.assertEqual(rejected.status_code, 200)
        self.assertIn(b"Correo o contrase", rejected.data)
        for _ in range(4):
            login_token = self.csrf(user_b, "/login")
            rejected = user_b.post("/login", data={
                "csrf_token": login_token, "email": "persona-b@example.test", "password": "incorrecta"
            })
            self.assertEqual(rejected.status_code, 200)
        login_token = self.csrf(user_b, "/login")
        throttled = user_b.post("/login", data={
            "csrf_token": login_token, "email": "persona-b@example.test", "password": "ClaveSeguraB123"
        })
        self.assertEqual(throttled.status_code, 429)
        self.assertIn("Retry-After", throttled.headers)
        throttle_key = ("persona-b@example.test", "127.0.0.1")
        web._login_failures.pop(throttle_key, None)
        web._login_blocked_until.pop(throttle_key, None)
        login_token = self.csrf(user_b, "/login")
        accepted = user_b.post("/login", data={
            "csrf_token": login_token, "email": "persona-b@example.test", "password": "ClaveSeguraB123"
        })
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(user_b.get("/dashboard").status_code, 200)

    def test_additive_migration_preserves_existing_records(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL, incident_json TEXT NOT NULL, category TEXT NOT NULL,
                    probabilities_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
                INSERT INTO users(email,password_hash) VALUES('old@example.test','existing-hash');
                INSERT INTO predictions(user_id,incident_json,category,probabilities_json)
                    VALUES(1,'{}','LEGACY','{}');
            """)
            connection.commit()
        finally:
            connection.close()
        original_path = web.USER_DB_PATH
        try:
            web.USER_DB_PATH = legacy_path
            web.ensure_user_database()
        finally:
            web.USER_DB_PATH = original_path
        connection = sqlite3.connect(legacy_path)
        try:
            self.assertEqual(connection.execute("SELECT name,email,password_hash FROM users").fetchone(),
                             ("", "old@example.test", "existing-hash"))
            self.assertEqual(connection.execute("SELECT user_id,category FROM predictions").fetchone(),
                             (1, "LEGACY"))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
