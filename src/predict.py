"""Load the saved model pipeline and predict a cybercrime category."""
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/best_model.joblib"
INFO_PATH = ROOT / "models/best_model_info.json"


def predict_incident(incident: dict, model_path: str | Path = MODEL_PATH) -> dict:
    """Return a predicted category and its per-class probability estimates."""
    if not isinstance(incident, dict) or not incident:
        raise ValueError("incident must be a non-empty dictionary of model features.")
    model = joblib.load(model_path)
    required = list(model.feature_names_in_)
    missing = [field for field in required if field not in incident]
    if missing:
        raise ValueError(f"Required features are missing: {missing}")
    frame = pd.DataFrame([{field: incident[field] for field in required}], columns=required)
    category = model.predict(frame)[0]
    result = {"prediction": str(category)}
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(frame)[0]
        result["probabilities"] = {
            str(label): float(probability)
            for label, probability in zip(model.classes_, probabilities)
        }
    return result


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m src.predict '{\"criminalidad\":...}'")
    print(json.dumps(predict_incident(json.loads(sys.argv[1])), ensure_ascii=False, indent=2))
