"""URL-only phishing prediction contract used by the Flask application."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import joblib
from src.phishing_features import make_url_feature_frame, normalize_url_text

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/phishing_detector.joblib"
INFO_PATH = ROOT / "models/phishing_detector_info.json"


@lru_cache(maxsize=1)
def _load_model(path: str):
    return joblib.load(path)


def predict_url(url: str, model_path: str | Path = MODEL_PATH) -> dict:
    """Classify a URL string without opening it or fetching any page content.

    Returns ``prediction`` (``phishing`` or ``legitimate``), ``is_phishing``,
    and per-class classifier probability estimates.
    """
    normalized_url = normalize_url_text(url)
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Phishing model is unavailable at {path}. Train it with python -m src.train_phishing.")
    model = _load_model(str(path.resolve()))
    steps = getattr(model, "named_steps", {})
    if "scale" in steps or "url_features" in steps:
        features = make_url_feature_frame([normalized_url])
    else:
        features = [normalized_url]
    class_values = [int(value) for value in model.classes_]
    predicted_value = int(model.predict(features)[0])
    probabilities = model.predict_proba(features)[0]
    label_names = {0: "legitimate", 1: "phishing"}
    return {
        "prediction": label_names[predicted_value],
        "is_phishing": predicted_value == 1,
        "probabilities": {
            label_names[class_value]: float(probability)
            for class_value, probability in zip(class_values, probabilities)
        },
        "model": "phishing_detection",
        "input_url": normalized_url,
        "disclaimer": "URL-text estimate only; page content was not inspected.",
    }


if __name__ == "__main__":
    import argparse

    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="HTTP or HTTPS URL; it will not be opened")
    args = parser.parse_args()
    print(json.dumps(predict_url(args.url), indent=2, ensure_ascii=False))
