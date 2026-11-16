"""Single prediction with the location benchmark model (used by tests and scripts)."""
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/best_model.joblib"
INFO_PATH = ROOT / "models/best_model_info.json"


def predict_incident(incident: dict, model_path: str | Path = MODEL_PATH) -> dict:
    """Predict the category. Every feature used by the model is required."""
    if not isinstance(incident, dict) or not incident:
        raise ValueError("incident must be a dictionary with the model features.")
    model = joblib.load(model_path)
    required = list(model.feature_names_in_)
    missing = [field for field in required if field not in incident]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    frame = pd.DataFrame([{field: incident[field] for field in required}], columns=required)
    result = {"prediction": str(model.predict(frame)[0])}
    if hasattr(model, "predict_proba"):
        result["probabilities"] = {str(label): float(p) for label, p
                                   in zip(model.classes_, model.predict_proba(frame)[0])}
    return result


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m src.predict '{\"criminality\": ...}'")
    print(json.dumps(predict_incident(json.loads(sys.argv[1])), indent=2))
