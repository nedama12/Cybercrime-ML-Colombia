"""Prediction helper for the aggregated location benchmark.

This is not the incident narrative classifier (Astrith). It requires all features
stored in the fitted scikit-learn pipeline.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "best_model.joblib"


def predict_incident(incident: dict, model_path: str | Path = MODEL_PATH) -> dict:
    if not isinstance(incident, dict) or not incident:
        raise ValueError("incident must be a non-empty dictionary")

    model = joblib.load(model_path)
    required = list(getattr(model, "feature_names_in_", []))
    if not required:
        raise ValueError("The saved model does not expose feature_names_in_")

    missing = [name for name in required if name not in incident]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    frame = pd.DataFrame([{name: incident[name] for name in required}], columns=required)
    prediction = model.predict(frame)[0]
    result = {"prediction": str(prediction)}

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(frame)[0]
        labels = getattr(model, "classes_", range(len(probabilities)))
        result["probabilities"] = {
            str(label): float(probability)
            for label, probability in zip(labels, probabilities)
        }
    return result
