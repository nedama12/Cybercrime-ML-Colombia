"""Data drift and live performance checks.

* Input drift: Population Stability Index (PSI) between the training distribution of each
  feature (models/reference_stats.json) and the inputs received in production.
      PSI < 0.10 stable · 0.10-0.25 moderate change · > 0.25 significant change
* Prediction drift: share of URLs predicted as phishing vs the training phishing rate.
* Live performance: latest prediction of each closed case vs the analyst verdict.
"""
import math

PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25
MIN_SAMPLE = 30
MAX_F1_DROP = 0.05
MIN_RECALL = 0.90


def psi(expected_props, edges, values):
    """PSI for one feature. `edges` uses None for -inf/+inf (see build_reference_stats.py)."""
    bounds = [-math.inf if e is None and i == 0 else math.inf if e is None else e
              for i, e in enumerate(edges)]
    counts = [0] * (len(bounds) - 1)
    for v in values:
        for i in range(len(counts)):
            # numpy.histogram semantics: [a, b) except the last bin, which is [a, b]
            if bounds[i] <= v < bounds[i + 1] or (i == len(counts) - 1 and v == bounds[-1]):
                counts[i] += 1
                break
    n = len(values) or 1
    total = 0.0
    for expected, count in zip(expected_props, counts):
        actual = count / n
        e, a = max(expected, 1e-4), max(actual, 1e-4)  # avoid log(0)
        total += (a - e) * math.log(a / e)
    return total


def psi_status(value):
    if value is None:
        return "insufficient data"
    if value > PSI_SIGNIFICANT:
        return "significant"
    if value > PSI_MODERATE:
        return "moderate"
    return "stable"


def input_drift(predictions, reference):
    """predictions: recent Prediction rows. Returns one row per monitored feature."""
    feats = (reference or {}).get("features", {})
    rows = []
    for name, ref in feats.items():
        values = [p.features[name] for p in predictions if name in p.features]
        value = psi(ref["bin_proportions"], ref["bin_edges"], values) if len(values) >= MIN_SAMPLE else None
        mean = sum(values) / len(values) if values else None
        rows.append({"feature": name, "n": len(values), "psi": value, "status": psi_status(value),
                     "train_mean": ref["mean"], "recent_mean": mean})
    return sorted(rows, key=lambda r: (r["psi"] is None, -(r["psi"] or 0)))


def prediction_drift(predictions, reference):
    if not predictions:
        return None
    rate = sum(p.label == "phishing" for p in predictions) / len(predictions)
    return {"recent_rate": rate, "training_rate": (reference or {}).get("phishing_rate"), "n": len(predictions)}


def live_performance(cases):
    """Classification metrics of the model against analyst verdicts (closed cases only)."""
    pairs = [(c.latest_prediction.label == "phishing", c.actual_label == "phishing")
             for c in cases if c.actual_label and c.latest_prediction]
    if not pairs:
        return None
    tp = sum(p and a for p, a in pairs)
    fp = sum(p and not a for p, a in pairs)
    fn = sum(a and not p for p, a in pairs)
    tn = sum(not p and not a for p, a in pairs)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    return {"n": len(pairs), "accuracy": (tp + tn) / len(pairs), "precision": precision,
            "recall": recall, "f1": f1, "confusion": [[tn, fp], [fn, tp]]}


def alerts(drift_rows, performance, offline_metrics, error_rate, p95_ms):
    """Rules that trigger a review or retraining (documented in CRISP-ML phase 6)."""
    found = []
    significant = [r["feature"] for r in drift_rows if r["status"] == "significant"]
    if significant:
        found.append(("danger", f"Significant input drift (PSI > {PSI_SIGNIFICANT}) in: {', '.join(significant)}."))
    if performance and performance["n"] >= MIN_SAMPLE:
        offline_f1 = (offline_metrics or {}).get("f1")
        if performance["f1"] is not None and offline_f1 and offline_f1 - performance["f1"] > MAX_F1_DROP:
            found.append(("danger", f"Live F1 {performance['f1']:.3f} is more than {MAX_F1_DROP} below the test F1 {offline_f1:.3f}: schedule retraining."))
        if performance["recall"] is not None and performance["recall"] < MIN_RECALL:
            found.append(("warning", f"Live recall {performance['recall']:.3f} is below the success criterion {MIN_RECALL}."))
    if error_rate is not None and error_rate > 0.02:
        found.append(("warning", f"Server error rate {error_rate:.1%} is above 2%."))
    if p95_ms is not None and p95_ms > 500:
        found.append(("warning", f"p95 response time {p95_ms:.0f} ms is above the 500 ms target."))
    return found
