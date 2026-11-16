"""Read-only smoke checks for installed model artifacts.

Checks the crime model and optional phishing model when their data/artifacts exist.
Checks the incident report classifier separately when its artifact and holdout exist.
This script does not train models or overwrite artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def _check_classifier(path: Path, label: str) -> None:
    if not path.exists():
        print(f"SKIP {label}: artifact not found ({path.relative_to(ROOT)})")
        return
    model = joblib.load(path)
    if not hasattr(model, "predict"):
        raise TypeError(f"{label} artifact has no predict() method: {path}")
    print(f"OK {label}: loaded {path.name}")


def main() -> None:
    # Aggregated location benchmark: distinct from Astrith.
    crime_path = MODELS / "best_model.joblib"
    sample_path = ROOT / "data/processed/delitos_procesado.csv"
    if not sample_path.exists():
        sample_path = ROOT / "data/processed/crimes_processed.csv"

    if crime_path.exists() and sample_path.exists():
        model = joblib.load(crime_path)
        sample = pd.read_csv(sample_path, nrows=1)
        expected = list(getattr(model, "feature_names_in_", []))
        if expected:
            missing = sorted(set(expected) - set(sample.columns))
            if missing:
                raise ValueError(f"Crime sample is missing model inputs: {missing}")
            prediction = model.predict(sample.loc[:, expected])[0]
        else:
            prediction = model.predict(sample)[0]
        print(f"OK location benchmark: {prediction}")
    else:
        print("SKIP location benchmark: model artifact or processed sample is missing")

    # Separate URL-only phishing model.
    phishing_path = MODELS / "phishing_detector.joblib"
    if phishing_path.exists():
        _check_classifier(phishing_path, "URL phishing model")
    else:
        print("SKIP URL phishing model: artifact not found")

    # Incident narrative classifier (Astrith in the project workflow).
    report_path = MODELS / "report_classifier.joblib"
    if report_path.exists():
        _check_classifier(report_path, "incident narrative classifier / Astrith")
        holdout_path = ROOT / "data/reports/realistic_holdout.csv"
        if holdout_path.exists():
            from src.report_model import classify_report

            holdout = pd.read_csv(holdout_path, keep_default_na=False)
            hits = 0
            for record in holdout.to_dict("records"):
                result = classify_report(
                    record["description"],
                    record["channel"],
                    record["affected"].split(";") if record.get("affected") else [],
                )
                hits += result.get("category") == record.get("category")
            print(f"OK Astrith realistic holdout: {hits}/{len(holdout)} correct")
        else:
            print("SKIP Astrith holdout: data/reports/realistic_holdout.csv not found")
    else:
        print("SKIP Astrith: models/report_classifier.joblib not found")

    print("Model smoke checks finished. No model artifacts were modified.")


if __name__ == "__main__":
    main()
