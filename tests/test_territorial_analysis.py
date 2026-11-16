"""Regression checks for the territorial analysis data contract and Flask route."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import re

import pandas as pd

import app as web
from src.territorial_analysis import (
    CATEGORY_LABELS,
    FORECAST_YEARS,
    LEGAL_CATEGORIES,
    _filtered_crimes,
    build_analysis_context,
    load_data,
    normalize_location,
)


class TerritorialAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crimes, cls.municipal_rates, cls.department_rates = load_data()
        cls.sample = cls.crimes[cls.crimes["categoria"].isin(LEGAL_CATEGORIES)].iloc[0]

    def test_only_known_legal_categories_enter_analysis(self):
        filtered = _filtered_crimes({"scope": "national", "category": "all"}, "report")
        self.assertTrue(set(filtered["categoria"].unique()).issubset(set(CATEGORY_LABELS)))
        self.assertNotIn("NO_ESPECIFICADO", filtered["categoria"].unique())
        self.assertEqual(len(CATEGORY_LABELS), 8)

    def test_combined_filters_match_processed_rows(self):
        sample = self.sample
        filters = {
            "scope": "municipality",
            "department": str(sample["departamento_hecho"]),
            "municipality": str(sample["municipio_hecho"]),
            "category": str(sample["categoria"]),
        }
        filtered = _filtered_crimes(filters, "report")
        expected = self.crimes[
            (self.crimes["departamento_hecho"] == filters["department"])
            & (self.crimes["municipio_hecho"] == filters["municipality"])
            & (self.crimes["categoria"] == filters["category"])
        ]
        self.assertEqual(float(filtered["total_procesos"].sum()),
                         float(expected["total_procesos"].sum()))
        self.assertEqual(set(filtered["ano_denuncia"].dropna().astype(int)),
                         set(expected["ano_denuncia"].dropna().astype(int)))

    def test_event_and_report_years_use_their_own_fields(self):
        filters = {"scope": "national", "category": "all"}
        event = _filtered_crimes(filters, "event").groupby("ano_hechos")["total_procesos"].sum()
        report = _filtered_crimes(filters, "report").groupby("ano_denuncia")["total_procesos"].sum()
        self.assertNotEqual(event.to_dict(), report.to_dict())

    def test_empty_filter_combination_returns_a_page_state(self):
        legal_rows = self.crimes[self.crimes["categoria"].isin(LEGAL_CATEGORIES)]
        coverage = legal_rows.groupby(["departamento_hecho", "municipio_hecho"])[
            "categoria"].nunique().sort_values()
        department, municipality = map(str, coverage.index[0])
        present_categories = set(self.crimes.loc[
            (self.crimes["departamento_hecho"].astype(str) == department)
            & (self.crimes["municipio_hecho"].astype(str) == municipality), "categoria"])
        rare_category = next(
            category for category in LEGAL_CATEGORIES
            if category not in present_categories)
        context = build_analysis_context({
            "scope": "municipality", "department": department,
            "municipality": municipality, "category": rare_category,
            "basis": "report", "compare_level": "municipality",
        })
        self.assertTrue(context["no_data"])
        self.assertEqual(context["history"], [])
        self.assertIsNone(context["forecast"])

    def test_forecast_excludes_partial_2026_and_returns_fixed_horizon(self):
        context = build_analysis_context({
            "scope": "national", "category": "all", "basis": "report",
            "year": "2025", "compare_level": "department",
        })
        self.assertIsNotNone(context["forecast"])
        forecast = context["forecast"]
        self.assertTrue(forecast["available"])
        self.assertEqual(forecast["trained_through"], 2025)
        self.assertEqual(tuple(row["year"] for row in forecast["future"]), FORECAST_YEARS)
        self.assertNotIn(2026, forecast["validation_years"])
        self.assertEqual(set(forecast["scores"]), {"three_year_mean", "linear_trend"})

    def test_population_rate_is_limited_to_report_year_matching(self):
        self.assertEqual(normalize_location("Bogotá, D. C."), "BOGOTA D C")
        self.assertTrue(set(self.department_rates["report_year"].astype(int)).issubset(
            set(range(2018, 2026))))
        self.assertEqual(self.department_rates.duplicated(
            ["department_norm", "report_year"]).sum(), 0)
        self.assertEqual(self.municipal_rates.duplicated(
            ["department_norm", "municipality_norm", "report_year"]).sum(), 0)

    def test_territorial_route_renders_with_temporary_database(self):
        original_db_path = web.USER_DB_PATH
        with tempfile.TemporaryDirectory(prefix="territorial-route-") as directory:
            web.USER_DB_PATH = Path(directory) / "users.sqlite3"
            web.app.config.update(TESTING=True, SECRET_KEY="territorial-test-secret")
            try:
                client = web.app.test_client()
                web.ensure_user_database()
                with web.connect_db() as connection:
                    connection.execute(
                        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                        ("Test Analyst", "territorial@example.test", "test-only", "analyst"),
                    )
                with client.session_transaction() as session:
                    session["user_id"] = 1
                response = client.get("/territorial-analysis?scope=national&basis=report&year=2025")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Cybercrime Territorial and Temporal Analysis", response.data)
                self.assertIn(b"Backtest method comparison", response.data)
                self.assertIn(b"Mobile terminal manipulation", response.data)

                for route in ("/", "/dataset", "/preprocessing", "/models", "/evaluation", "/reports"):
                    self.assertEqual(client.get(route).status_code, 200, route)

                phishing_form = client.get("/prediction?model=phishing")
                self.assertEqual(phishing_form.status_code, 200)
                token = re.search(rb'name="csrf_token" value="([^"]+)"', phishing_form.data)
                self.assertIsNotNone(token)
                phishing_result = client.post("/prediction", data={
                    "csrf_token": token.group(1).decode("utf-8"),
                    "model": "phishing", "url": "https://example.com/",
                })
                self.assertEqual(phishing_result.status_code, 200)
                self.assertIn(b"saved to your account", phishing_result.data)
                self.assertEqual(client.get("/history").status_code, 200)
            finally:
                web.USER_DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
