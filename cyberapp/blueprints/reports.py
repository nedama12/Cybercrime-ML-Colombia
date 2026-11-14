"""Reports and indicators for analysts and administrators, plus CSV exports."""
import csv
import io
from collections import Counter
from datetime import timedelta

import pandas as pd
from flask import Blueprint, Response, current_app, render_template, request

from ..models import CHANNELS, CaseStatus, Prediction, Role, UrlCase, utcnow
from ..security import role_required

bp = Blueprint("reports", __name__, url_prefix="/reports")

PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}


def _aware(dt):
    """SQLite returns naive datetimes; PostgreSQL returns aware ones. Normalize to UTC."""
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def _period():
    key = request.args.get("period", "30")
    key = key if key in PERIODS else "30"
    days = PERIODS[key]
    return key, (utcnow() - timedelta(days=days)) if days else None


def _colombia_context():
    """Context indicators from the processed open data (Data Engineering outputs)."""
    data_dir = current_app.config["DATA_DIR"]
    try:
        rates = pd.read_csv(data_dir / "rates_department_year.csv")
        year = int(rates["report_year"].max())
        top = (rates[rates["report_year"] == year].sort_values("rate_100k", ascending=False).head(10))
        trend = pd.read_csv(data_dir / "summary_year_category.csv")
        trend = trend[(trend["report_year"] >= 2015) & (trend["report_year"] <= year)]
        return {
            "year": year,
            "top_departments": top[["department_norm", "total_cases", "rate_100k"]].to_dict("records"),
            "trend_years": trend["report_year"].tolist(),
            "trend_phishing": trend["PHISHING_SPOOFING"].tolist(),
            "trend_theft": trend["ELECTRONIC_THEFT"].tolist(),
        }
    except (OSError, KeyError, ValueError) as exc:
        current_app.logger.warning("Colombia context data not available: %s", exc)
        return None


@bp.route("/")
@role_required(Role.ANALYST, Role.ADMIN)
def dashboard():
    period, since = _period()
    cases_q, preds_q = UrlCase.query, Prediction.query
    if since:
        cases_q = cases_q.filter(UrlCase.created_at >= since)
        preds_q = preds_q.filter(Prediction.created_at >= since)
    cases, predictions = cases_q.all(), preds_q.all()

    closed = [c for c in cases if c.status == CaseStatus.CLOSED]
    judged = [c for c in closed if c.model_agrees is not None]
    hours = [(_aware(c.closed_at) - _aware(c.created_at)).total_seconds() / 3600
             for c in closed if c.closed_at]
    kpis = {
        "cases": len(cases),
        "open": sum(c.is_open for c in cases),
        "high_open": sum(c.is_open and c.priority == "high" for c in cases),
        "closed": len(closed),
        "confirmed_phishing": sum(c.actual_label == "phishing" for c in closed),
        "predictions": len(predictions),
        "agreement": (sum(c.model_agrees for c in judged) / len(judged)) if judged else None,
        "judged": len(judged),
        "avg_resolution_hours": (sum(hours) / len(hours)) if hours else None,
        "avg_latency_ms": (sum(p.latency_ms for p in predictions) / len(predictions)) if predictions else None,
    }

    weeks = Counter(_aware(c.created_at).strftime("%G-W%V") for c in cases)
    channels = Counter(c.channel_label for c in cases)
    charts = {
        "weeks": sorted(weeks), "week_counts": [weeks[w] for w in sorted(weeks)],
        "risk_labels": ["high", "medium", "low", "pending"],
        "risk_counts": [sum(c.priority == r for c in cases) for r in ("high", "medium", "low", "pending")],
        "status_labels": list(CaseStatus.LABELS.values()),
        "status_counts": [sum(c.status == s for c in cases) for s in CaseStatus.LABELS],
        "channel_labels": [label for _, label in CHANNELS],
        "channel_counts": [channels[label] for _, label in CHANNELS],
    }
    top_domains = Counter(c.domain for c in cases).most_common(8)
    return render_template("reports/dashboard.html", kpis=kpis, charts=charts, period=period,
                           top_domains=top_domains, colombia=_colombia_context())


def _safe(value):
    """Neutralize spreadsheet formulas in exported text (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe(v) for v in row])
    return Response(buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@bp.route("/export/cases.csv")
@role_required(Role.ANALYST, Role.ADMIN)
def export_cases():
    cases = UrlCase.query.order_by(UrlCase.id).all()
    rows = [(c.id, c.created_at.isoformat(), c.url, c.domain, c.channel, c.status, c.priority,
             c.reporter.username, c.assignee.username if c.assignee else "",
             c.latest_prediction.probability if c.latest_prediction else "",
             c.latest_prediction.model_version if c.latest_prediction else "",
             c.actual_label or "", c.action_taken or "", c.closed_at.isoformat() if c.closed_at else "",
             int(c.is_simulated)) for c in cases]
    current_app.logger.info("Cases exported (%d rows)", len(rows))
    return _csv_response("cases.csv", ["id", "created_at", "url", "domain", "channel", "status", "priority",
                                       "reporter", "assignee", "phishing_probability", "model_version",
                                       "actual_label", "action_taken", "closed_at", "is_simulated"], rows)


@bp.route("/export/predictions.csv")
@role_required(Role.ANALYST, Role.ADMIN)
def export_predictions():
    preds = Prediction.query.order_by(Prediction.id).all()
    rows = [(p.id, p.created_at.isoformat(), p.user.username, p.case_id or "", p.url, p.probability,
             p.label, p.risk_level, p.threshold, p.model_name, p.model_version, p.latency_ms,
             int(p.is_simulated)) for p in preds]
    return _csv_response("predictions.csv", ["id", "created_at", "user", "case_id", "url", "probability",
                                             "label", "risk_level", "threshold", "model_name",
                                             "model_version", "latency_ms", "is_simulated"], rows)
