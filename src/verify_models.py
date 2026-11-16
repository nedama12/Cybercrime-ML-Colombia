"""Read-only smoke checks for the installed crime and phishing models.

This command loads artifacts and performs one in-memory prediction per model.
It does not train models or write/replace any artifact.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

from src.crime_features import CRIME_INPUT_FEATURES
from src.phishing_predict import predict_url

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    crime_path = ROOT / "models/best_model.joblib"
    sample_path = ROOT / "data/processed/delitos_procesado.csv"
    model = joblib.load(crime_path)
    sample = pd.read_csv(sample_path, nrows=1)
    missing = sorted(set(CRIME_INPUT_FEATURES) - set(sample.columns))
    if missing:
        raise ValueError(f"Crime sample is missing model inputs: {missing}")
    prediction = model.predict(sample.loc[:, CRIME_INPUT_FEATURES])[0]
    print(f"Cybercrime model loaded and predicted: {prediction}")

    phishing = predict_url("https://example.com/")
    print(f"Phishing model loaded and predicted: {phishing['prediction']}")
    print("Smoke check complete. No model artifacts were modified.")


if __name__ == "__main__":
    main()
