"""Check that every saved model loads and answers a real example.

Usage:  python -m src.verify_models
"""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.predict import predict_incident
from src.report_model import classify_report

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def main():
    for name in ("decision_tree", "random_forest", "logistic_regression", "best_model",
                 "report_classifier"):
        model = joblib.load(MODELS / f"{name}.joblib")
        assert hasattr(model, "predict") and hasattr(model, "predict_proba"), name

    info = json.loads((MODELS / "best_model_info.json").read_text(encoding="utf-8"))
    row = pd.read_csv(ROOT / info["dataset"], nrows=1).iloc[0][info["features"]].to_dict()
    benchmark = predict_incident(row)
    assert abs(sum(benchmark["probabilities"].values()) - 1.0) < 1e-6
    print(f"Location benchmark OK -> {benchmark['prediction']}")

    holdout = pd.read_csv(ROOT / "data/reports/realistic_holdout.csv", keep_default_na=False)
    hits = 0
    for record in holdout.to_dict("records"):
        result = classify_report(record["description"], record["channel"],
                                 record["affected"].split(";"))
        hits += result["category"] == record["category"]
    print(f"Report classifier OK -> {hits}/{len(holdout)} realistic holdout reports correct")


if __name__ == "__main__":
    main()
