"""Leakage-safe transformations for the aggregated Colombian crime classifier."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin


CRIME_INPUT_FEATURES = [
    "criminalidad", "departamento_hecho", "municipio_hecho", "seccional",
    "ano_hechos", "ano_entrada", "ano_denuncia", "anio_parcial",
]

CRIME_NUMERIC_FEATURES = [
    "criminalidad", "ano_hechos", "ano_entrada", "ano_denuncia",
    "delay_event_to_entry", "delay_event_to_report", "delay_entry_to_report",
]

CRIME_CATEGORICAL_FEATURES = [
    "departamento_hecho", "municipio_hecho", "seccional", "geo_unit", "event_period",
]

CRIME_HIST_CATEGORICAL_FEATURES = [
    "departamento_hecho", "seccional", "event_period",
]


class CrimeFeatureBuilder(BaseEstimator, TransformerMixin):
    """Create only input-available temporal and geographic features.

    ``articulo``, ``delito``, legal-process outcomes, and aggregate counts are
    intentionally outside this transformer's input schema.
    """

    def fit(self, X, y=None):
        frame = self._as_frame(X)
        missing = sorted(set(CRIME_INPUT_FEATURES) - set(frame.columns))
        if missing:
            raise ValueError(f"Required crime input features are missing: {missing}")
        self.feature_names_in_ = np.asarray(frame.columns, dtype=object)
        self.n_features_in_ = len(self.feature_names_in_)
        return self

    def transform(self, X):
        frame = self._as_frame(X)
        missing = sorted(set(CRIME_INPUT_FEATURES) - set(frame.columns))
        if missing:
            raise ValueError(f"Required crime input features are missing: {missing}")

        for name in ("criminalidad", "ano_hechos", "ano_entrada", "ano_denuncia"):
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        frame["delay_event_to_entry"] = frame["ano_entrada"] - frame["ano_hechos"]
        frame["delay_event_to_report"] = frame["ano_denuncia"] - frame["ano_hechos"]
        frame["delay_entry_to_report"] = frame["ano_denuncia"] - frame["ano_entrada"]

        department = frame["departamento_hecho"].fillna("Unknown").astype(str)
        municipality = frame["municipio_hecho"].fillna("Unknown").astype(str)
        frame["geo_unit"] = department + " :: " + municipality

        event_year = frame["ano_hechos"]
        frame["event_period"] = np.select(
            [event_year <= 2014, event_year <= 2019, event_year <= 2023, event_year <= 2026],
            ["2010-2014", "2015-2019", "2020-2023", "2024-2026"],
            default="2027+",
        )
        output = frame[CRIME_NUMERIC_FEATURES + CRIME_CATEGORICAL_FEATURES].copy()
        for name in CRIME_CATEGORICAL_FEATURES:
            output[name] = output[name].astype("object")
        return output

    @staticmethod
    def _as_frame(X):
        if isinstance(X, pd.DataFrame):
            return X.copy()
        raise TypeError("CrimeFeatureBuilder requires a pandas DataFrame input.")
