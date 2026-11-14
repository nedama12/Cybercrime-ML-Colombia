"""Inference workflow: URL -> features -> model -> stored prediction -> business decision."""
import json
import logging

from flask import current_app

from ..extensions import db
from ..models import CaseStatus, Prediction
from .features import build_model_input, load_json
from .service import get_model_service

logger = logging.getLogger("cyberapp.inference")

# What the organization does with each risk level (connects the model to a decision).
RECOMMENDATIONS = {
    "high": {
        "title": "Block and escalate",
        "action": "Block the URL in the mail and web filters, warn the users who may have received "
                  "it and escalate to the security team. Close the case once the block is confirmed.",
        "meaning": "The model is very confident that this link imitates a legitimate site to steal "
                   "data or money.",
    },
    "medium": {
        "title": "Manual review required",
        "action": "Do not block automatically. An analyst must inspect the domain (age, owner, "
                  "content) before deciding.",
        "meaning": "The URL looks more like phishing than legitimate, but the model is not certain.",
    },
    "low": {
        "title": "Monitor",
        "action": "No blocking is needed. Keep the report for reference and close it if the analyst "
                  "agrees with the model.",
        "meaning": "The URL looks like the legitimate URLs the model learned from.",
    },
}

LIMITATIONS = (
    "The model only analyzes the text of the URL; it does not open the page. A low risk does not "
    "guarantee that the site is safe, and the final decision always belongs to an analyst."
)


class MissingFeatures(Exception):
    def __init__(self, missing):
        super().__init__(", ".join(missing))
        self.missing = missing


def _reference(name):
    """Cache reference files (TLD table, training statistics) once per application."""
    cache = current_app.extensions.setdefault("ml_reference", {})
    if name not in cache:
        cache[name] = load_json(current_app.config["MODEL_DIR"] / name)
    return cache[name]


def tld_table():
    return _reference("tld_legitimate_prob.json") or {}


def reference_stats():
    return _reference("reference_stats.json") or {}


def classify(url, user, case=None, manual=None, simulated=False):
    """Run the model for a URL and store the prediction. Raises MissingFeatures or RuntimeError."""
    service = get_model_service()
    if not service.ready:
        raise RuntimeError("No model is deployed. " + (service.error or ""))
    values, sources, missing = build_model_input(url, service.features, manual, tld_table())
    if missing:
        raise MissingFeatures(missing)

    outcome = service.predict(values)
    prediction = Prediction(
        case=case, user_id=user.id, url=url, probability=outcome.probability, label=outcome.label,
        risk_level=outcome.risk_level, threshold=outcome.threshold, model_name=outcome.model_name,
        model_version=outcome.model_version, features_json=json.dumps(values),
        sources_json=json.dumps(sources), latency_ms=outcome.latency_ms, is_simulated=simulated,
    )
    db.session.add(prediction)
    if case is not None:
        # Business rule: the model result sets the priority and moves a new case forward.
        case.priority = outcome.risk_level
        if case.status == CaseStatus.NEW:
            case.status = CaseStatus.CLASSIFIED
    db.session.commit()
    logger.info("Prediction %s case=%s p=%.4f risk=%s model=%s latency=%.1fms user=%s",
                prediction.id, case.id if case else "-", outcome.probability, outcome.risk_level,
                outcome.model_version, outcome.latency_ms, user.username)
    return prediction


def explain(prediction, top=6):
    """Compare the URL's features with the training medians of each class.

    Features are ordered by the model's global importance when Model Engineering reports it
    (model_metadata.json -> feature_importance); otherwise by how far the value is from the
    legitimate median. This is a descriptive aid, not a causal explanation.
    """
    stats = reference_stats().get("features", {})
    importance = {item["feature"]: item["importance"] for item in
                  get_model_service().metadata.get("feature_importance", [])}
    rows = []
    for name, value in prediction.features.items():
        ref = stats.get(name)
        if not ref:
            continue
        legit, phish = ref["median_legitimate"], ref["median_phishing"]
        spread = ref["std"] or 1.0
        closer = "phishing" if abs(value - phish) < abs(value - legit) else "legitimate"
        if legit == phish:
            closer = "neutral"
        rows.append({
            "feature": name, "value": value, "median_legitimate": legit,
            "median_phishing": phish, "closer_to": closer,
            "importance": importance.get(name),
            "deviation": abs(value - legit) / spread,
        })
    key = (lambda r: r["importance"] or 0) if importance else (lambda r: r["deviation"])
    return sorted(rows, key=key, reverse=True)[:top]
