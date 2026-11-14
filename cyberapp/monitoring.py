"""Operational logging: every request (endpoint, status, response time, user) and errors."""
import logging
import time
from collections import defaultdict
from datetime import timedelta

from flask import g, got_request_exception, request
from flask_login import current_user

from .extensions import db
from .ml.drift import alerts, input_drift, live_performance, prediction_drift
from .models import CaseStatus, Prediction, RequestLog, UrlCase, utcnow

logger = logging.getLogger("cyberapp.requests")
SKIP_ENDPOINTS = {"static", "model.health"}


def init_request_logging(app):
    @app.before_request
    def _start_timer():
        g.request_started = time.perf_counter()

    def _remember_error(sender, exception, **extra):
        g.request_error = f"{type(exception).__name__}: {exception}"[:1000]
        logger.exception("Unhandled error on %s %s", request.method, request.path)

    got_request_exception.connect(_remember_error, app, weak=False)

    @app.after_request
    def _log_request(response):
        if request.endpoint in SKIP_ENDPOINTS or "request_started" not in g:
            return response
        latency = (time.perf_counter() - g.request_started) * 1000
        user_id = current_user.get_id() if current_user and current_user.is_authenticated else None
        try:
            db.session.rollback()  # never persist half-finished work from a failed request
            db.session.add(RequestLog(
                method=request.method, path=request.path[:255], endpoint=(request.endpoint or "")[:80],
                status_code=response.status_code, latency_ms=round(latency, 2),
                user_id=int(user_id) if user_id else None, error=g.get("request_error")))
            db.session.commit()
        except Exception:  # noqa: BLE001 - monitoring must never break the response
            db.session.rollback()
            logger.warning("Could not store the request log", exc_info=True)
        logger.info("%s %s %s %.1fms", request.method, request.path, response.status_code, latency)
        return response


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def operational_review(model_service, reference, days=7, window=200, include_simulated=True):
    """Collect every monitoring indicator in one dictionary (used by the page and the CLI)."""
    since = utcnow() - timedelta(days=days)
    logs = RequestLog.query.filter(RequestLog.created_at >= since).all()
    preds_q = Prediction.query
    cases_q = UrlCase.query.filter_by(status=CaseStatus.CLOSED)
    if not include_simulated:
        preds_q = preds_q.filter_by(is_simulated=False)
        cases_q = cases_q.filter_by(is_simulated=False)
    recent = preds_q.order_by(Prediction.created_at.desc()).limit(window).all()
    period_preds = preds_q.filter(Prediction.created_at >= since).all()

    latencies = [r.latency_ms for r in logs]
    errors = [r for r in logs if r.status_code >= 500]
    error_rate = len(errors) / len(logs) if logs else None
    p95 = percentile(latencies, 0.95)

    by_day = defaultdict(list)
    for r in logs:
        by_day[r.created_at.strftime("%Y-%m-%d")].append(r.latency_ms)
    risk_by_day = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0})
    for p in period_preds:
        risk_by_day[p.created_at.strftime("%Y-%m-%d")][p.risk_level] += 1
    days_axis = sorted(set(by_day) | set(risk_by_day))

    drift_rows = input_drift(recent, reference)
    performance = live_performance(cases_q.all())
    offline = (model_service.metadata.get("metrics") or {}).get("test")
    return {
        "days": days, "window": window, "include_simulated": include_simulated,
        "model": model_service.status(),
        "requests": len(logs), "errors": len(errors), "error_rate": error_rate,
        "p50": percentile(latencies, 0.5), "p95": p95,
        "inference_p95": percentile([p.latency_ms for p in period_preds], 0.95),
        "predictions": len(period_preds),
        "simulated_predictions": sum(p.is_simulated for p in period_preds),
        "recent_errors": sorted(errors, key=lambda r: r.created_at, reverse=True)[:10],
        "drift": drift_rows, "prediction_drift": prediction_drift(recent, reference),
        "performance": performance, "offline": offline,
        "versions": sorted({p.model_version for p in period_preds}),
        "alerts": alerts(drift_rows, performance, offline, error_rate, p95),
        "chart": {
            "days": days_axis,
            "p95": [round(percentile(by_day[d], 0.95) or 0, 1) for d in days_axis],
            "requests": [len(by_day[d]) for d in days_axis],
            "high": [risk_by_day[d]["high"] for d in days_axis],
            "medium": [risk_by_day[d]["medium"] for d in days_axis],
            "low": [risk_by_day[d]["low"] for d in days_axis],
        },
    }
