"""Operational monitoring of the deployed information system.

Reads the request log, the inference history and the reports stored by the
Flask application and returns the indicators shown on /admin/operations:
errors, response times, inference volume and latency, model versions in use,
agreement between predictions and the categories confirmed by analysts, and
input drift (PSI) against the training reference.
"""
from __future__ import annotations

import math

import numpy as np

# Same thresholds as the Activity 1 monitoring plan (src/monitoring.py).
THRESHOLDS = {"psi_warning": 0.10, "psi_alert": 0.25, "agreement_min": 0.80,
              "low_confidence_max": 0.25, "p95_latency_ms_max": 500, "error_rate_max": 0.02,
              "min_reports_for_drift": 30}


def psi(expected: dict, actual: dict) -> float:
    """Population Stability Index between two distributions over the same keys."""
    total = 0.0
    for key in expected:
        e, a = max(expected[key], 1e-4), max(actual.get(key, 0.0), 1e-4)
        total += (a - e) * math.log(a / e)
    return float(total)


def _percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def _share(rows: list, key: str) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def collect(connection, days: int, reference: dict) -> dict:
    since = f"-{int(days)} days"
    requests = connection.execute(
        "SELECT endpoint, status, duration_ms, error, created_at FROM request_log "
        "WHERE created_at >= datetime('now', ?)", (since,)).fetchall()
    durations = [r["duration_ms"] for r in requests]
    server_errors = [r for r in requests if r["status"] >= 500]
    endpoints: dict[str, list[float]] = {}
    for row in requests:
        endpoints.setdefault(row["endpoint"], []).append(row["duration_ms"])
    slowest = sorted(({"endpoint": name, "requests": len(values), "p95_ms": _percentile(values, 95)}
                      for name, values in endpoints.items()), key=lambda item: item["p95_ms"] or 0,
                     reverse=True)[:8]

    inferences = connection.execute(
        "SELECT source, model_version, predicted_category, confidence, needs_review, inference_ms, channel "
        "FROM inferences WHERE created_at >= datetime('now', ?)", (since,)).fetchall()
    inference_ms = [r["inference_ms"] for r in inferences]
    versions: dict[str, int] = {}
    sources: dict[str, int] = {}
    for row in inferences:
        versions[row["model_version"]] = versions.get(row["model_version"], 0) + 1
        sources[row["source"]] = sources.get(row["source"], 0) + 1

    reports = connection.execute(
        "SELECT channel, predicted_category, confirmed_category, user_agrees FROM incident_reports "
        "WHERE created_at >= datetime('now', ?)", (since,)).fetchall()
    confirmed = [r for r in reports if r["confirmed_category"]]
    answered = [r for r in reports if r["user_agrees"] is not None]
    by_category: dict[str, dict] = {}
    for row in confirmed:
        item = by_category.setdefault(row["confirmed_category"], {"confirmed": 0, "matches": 0})
        item["confirmed"] += 1
        item["matches"] += int(row["predicted_category"] == row["confirmed_category"])

    drift = {"reports": len(reports), "enough": len(reports) >= THRESHOLDS["min_reports_for_drift"]}
    if reference and reports:
        drift["channel"] = psi(reference.get("channel", {}), _share(reports, "channel"))
        drift["predicted_category"] = psi(reference.get("predicted_category", {}),
                                          _share(reports, "predicted_category"))

    metrics = {
        "days": days,
        "requests": len(requests), "server_errors": len(server_errors),
        "client_errors": sum(1 for r in requests if 400 <= r["status"] < 500),
        "error_rate": len(server_errors) / len(requests) if requests else None,
        "p50_ms": _percentile(durations, 50), "p95_ms": _percentile(durations, 95),
        "slowest": slowest,
        "recent_errors": [dict(r) for r in sorted(server_errors, key=lambda r: r["created_at"], reverse=True)[:10]],
        "inferences": len(inferences), "inference_sources": sources,
        "inference_p50_ms": _percentile(inference_ms, 50), "inference_p95_ms": _percentile(inference_ms, 95),
        "low_confidence_share": (sum(r["needs_review"] for r in inferences) / len(inferences)) if inferences else None,
        "mean_confidence": float(np.mean([r["confidence"] for r in inferences])) if inferences else None,
        "versions": versions,
        "confirmed": len(confirmed),
        "agreement": (sum(int(r["predicted_category"] == r["confirmed_category"]) for r in confirmed)
                      / len(confirmed)) if confirmed else None,
        "agreement_by_category": by_category,
        "citizen_agreement": (sum(r["user_agrees"] for r in answered) / len(answered)) if answered else None,
        "drift": drift,
    }
    metrics["alerts"] = alerts(metrics)
    return metrics


def alerts(m: dict) -> list[str]:
    found = []
    if m["error_rate"] is not None and m["error_rate"] > THRESHOLDS["error_rate_max"]:
        found.append(f"Server error rate {m['error_rate']:.1%} is above {THRESHOLDS['error_rate_max']:.0%}.")
    if m["inference_p95_ms"] is not None and m["inference_p95_ms"] > THRESHOLDS["p95_latency_ms_max"]:
        found.append(f"p95 inference time {m['inference_p95_ms']:.0f} ms is above "
                     f"{THRESHOLDS['p95_latency_ms_max']} ms.")
    if m["low_confidence_share"] is not None and m["low_confidence_share"] > THRESHOLDS["low_confidence_max"]:
        found.append(f"Low-confidence share {m['low_confidence_share']:.0%} is above "
                     f"{THRESHOLDS['low_confidence_max']:.0%}.")
    if m["agreement"] is not None and m["confirmed"] >= 10 and m["agreement"] < THRESHOLDS["agreement_min"]:
        found.append(f"Analyst agreement {m['agreement']:.0%} is below {THRESHOLDS['agreement_min']:.0%}.")
    drift = m["drift"]
    if drift.get("enough"):
        for name in ("channel", "predicted_category"):
            value = drift.get(name)
            if value is not None and value > THRESHOLDS["psi_alert"]:
                found.append(f"PSI of {name.replace('_', ' ')} {value:.2f} is above {THRESHOLDS['psi_alert']}.")
    return found
