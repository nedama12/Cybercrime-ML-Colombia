"""Loads the model selected in Model Engineering and runs inference on the server.

The model is delivered as two files in MODEL_DIR (see models/README.md):
  * model_metadata.json  - version, feature list, threshold and evaluation results
  * <artifact>.joblib    - a fitted scikit-learn Pipeline (preprocessing + classifier)
Keeping preprocessing inside the Pipeline guarantees that inference applies exactly the
transformations fitted on the training data.
"""
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

logger = logging.getLogger("cyberapp.model")

DEFAULT_ARTIFACT = "phishing_model.joblib"
METADATA_FILE = "model_metadata.json"
HIGH_RISK_PROBABILITY = 0.80


@dataclass
class PredictionOutcome:
    probability: float      # probability of the phishing class (0-1)
    label: str              # "phishing" or "legitimate"
    risk_level: str         # "low", "medium" or "high"
    threshold: float
    model_name: str
    model_version: str
    latency_ms: float


def risk_level(probability, threshold):
    """Business rule that turns the model probability into an operational priority."""
    if probability >= max(HIGH_RISK_PROBABILITY, threshold):
        return "high"
    if probability >= threshold:
        return "medium"
    return "low"


class ModelService:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self.model = None
        self.metadata = {}
        self.error = None
        self.loaded_at = None

    # ------------------------------------------------------------------ loading
    def load(self):
        """Load metadata and artifact. Failures are recorded, never raised, so the
        documentation and management modules keep working without a model."""
        self.model, self.error = None, None
        meta_path = self.model_dir / METADATA_FILE
        try:
            if not meta_path.exists():
                raise FileNotFoundError(f"{meta_path.name} not found in {self.model_dir}")
            self.metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            artifact = self.model_dir / self.metadata.get("artifact", DEFAULT_ARTIFACT)
            if not artifact.exists():
                raise FileNotFoundError(f"model artifact {artifact.name} not found")

            import joblib  # imported lazily: only needed when a model exists
            model = joblib.load(artifact)
            self._validate(model)
            self.model = model
            self.loaded_at = time.time()
            logger.info("Model loaded: %s %s (%d features)", self.name, self.version, len(self.features))
        except Exception as exc:  # noqa: BLE001 - any failure leaves the service "not ready"
            self.error = str(exc)
            logger.warning("Model not available: %s", exc)
        return self.ready

    def _validate(self, model):
        features = self.metadata.get("features")
        if not features or not isinstance(features, list):
            raise ValueError("model_metadata.json must list the input 'features'")
        if not hasattr(model, "predict_proba"):
            raise ValueError("the model must implement predict_proba")
        trained_on = getattr(model, "feature_names_in_", None)
        if trained_on is not None and list(trained_on) != list(features):
            raise ValueError("feature order in metadata does not match the trained model")
        positive = self.metadata.get("positive_class", 1)
        classes = list(getattr(model, "classes_", []))
        if classes and positive not in classes:
            raise ValueError(f"positive class {positive!r} not in model classes {classes}")
        expected = self.metadata.get("sklearn_version")
        if expected:
            import sklearn
            if sklearn.__version__ != expected:
                logger.warning("Model trained with scikit-learn %s, running %s",
                               expected, sklearn.__version__)

    # --------------------------------------------------------------- properties
    @property
    def ready(self):
        return self.model is not None

    @property
    def features(self):
        return list(self.metadata.get("features", []))

    @property
    def version(self):
        return str(self.metadata.get("version", "unknown"))

    @property
    def name(self):
        return self.metadata.get("model_name", "phishing-url-classifier")

    @property
    def threshold(self):
        return float(self.metadata.get("threshold", 0.5))

    def status(self):
        return {
            "ready": self.ready,
            "model_name": self.name if self.metadata else None,
            "model_version": self.version if self.metadata else None,
            "algorithm": self.metadata.get("algorithm"),
            "n_features": len(self.features),
            "error": self.error,
        }

    # ---------------------------------------------------------------- inference
    def predict(self, values):
        """values: dict feature -> number, containing every feature in metadata order."""
        if not self.ready:
            raise RuntimeError("No model is deployed. " + (self.error or ""))
        import pandas as pd

        missing = [f for f in self.features if f not in values]
        if missing:
            raise ValueError(f"missing features: {', '.join(missing)}")
        row = pd.DataFrame([[float(values[f]) for f in self.features]], columns=self.features)
        start = time.perf_counter()
        probabilities = self.model.predict_proba(row)[0]
        latency_ms = (time.perf_counter() - start) * 1000
        classes = list(getattr(self.model, "classes_", [0, 1]))
        probability = float(probabilities[classes.index(self.metadata.get("positive_class", 1))])
        label = "phishing" if probability >= self.threshold else "legitimate"
        return PredictionOutcome(
            probability=round(probability, 4), label=label,
            risk_level=risk_level(probability, self.threshold), threshold=self.threshold,
            model_name=self.name, model_version=self.version, latency_ms=round(latency_ms, 2),
        )


def init_model_service(app):
    service = ModelService(app.config["MODEL_DIR"])
    service.load()
    app.extensions["model_service"] = service
    return service


def get_model_service():
    return current_app.extensions["model_service"]
