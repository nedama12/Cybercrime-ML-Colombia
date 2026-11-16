"""Monitoring demo for the report classifier (CRISP-ML phase 6).

Runs the production model on a batch of SIMULATED operational reports over four
weeks and computes the indicators defined in the monitoring plan: volume,
confidence, low-confidence share, agreement with the (simulated) analyst label,
inference latency and data drift (PSI) against the training baseline stored in
models/report_reference_stats.json. Weeks 3-4 introduce new fraud wording and more
social-media reports on purpose, to show how drift and degradation are detected.

Every row is labelled `simulated = 1`. Real indicators of the platform are shown
in the analyst Review page.

Outputs: reports/monitoring/monitoring_report.json, monitoring_log.csv, monitoring.png
Usage:   python -m src.monitoring
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.build_seed_corpus import CATEGORIES, fill
from src.report_features import AFFECTED, CHANNELS
from src.report_model import classify_report, load_model

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "models/report_reference_stats.json"
OUT_DIR = ROOT / "reports/monitoring"
SEED = 7
REPORTS_PER_WEEK = 150
THRESHOLDS = {"psi_warning": 0.10, "psi_alert": 0.25, "agreement_min": 0.80,
              "low_confidence_max": 0.25, "p95_latency_ms_max": 500}

# New scam wording that did not exist in training (introduced in weeks 3 and 4).
EMERGING = [
    ("TRANSFER_FRAUD", "a cloned voice of my son made with AI asked me to send money and I did", "phone_call", ["money"]),
    ("PHISHING_SPOOFING", "I scanned a QR code in a parking lot that opened a fake payment page", "website_app", ["personal_data", "money"]),
    ("TRANSFER_FRAUD", "a crypto influencer on TikTok promised to double my money and I sent it", "social_media", ["money"]),
    ("ABUSIVE_ACCESS", "they hijacked my WhatsApp with a six digit code I shared by mistake", "sms_whatsapp", ["account"]),
]


def psi(expected: dict, actual: dict) -> float:
    """Population Stability Index between two distributions over the same keys."""
    total = 0.0
    for key in expected:
        e, a = max(expected[key], 1e-4), max(actual.get(key, 0.0), 1e-4)
        total += (a - e) * math.log(a / e)
    return float(total)


def simulate(rng: random.Random) -> pd.DataFrame:
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    rows = []
    for week in range(1, 5):
        drift = week >= 3
        for _ in range(REPORTS_PER_WEEK):
            if drift and rng.random() < 0.35:
                category, text, channel, affected = rng.choice(EMERGING)
            else:
                category = rng.choice(list(CATEGORIES))
                spec = CATEGORIES[category]
                text = fill(rng, rng.choice(spec["phrases"]))
                channel = rng.choices(list(spec["channels"]), weights=list(spec["channels"].values()))[0]
                if drift and rng.random() < 0.3:
                    channel = "social_media"
                affected = [a for a, p in spec["affected"].items() if rng.random() < p] or ["money"]
            started = time.perf_counter()
            result = classify_report(text, channel, affected)
            latency = (time.perf_counter() - started) * 1000
            rows.append({"simulated": 1, "week": week,
                         "timestamp": (start + timedelta(days=7 * (week - 1), minutes=rng.randint(0, 10079))).isoformat(),
                         "channel": channel, "affected": ";".join(affected), "description": text,
                         "predicted_category": result["category"], "confidence": round(result["confidence"], 4),
                         "needs_review": int(result["needs_review"]), "analyst_category": category,
                         "inference_ms": round(latency, 2), "model_version": result["model_version"]})
    return pd.DataFrame(rows)


def weekly_indicators(log: pd.DataFrame, reference: dict) -> list[dict]:
    weeks = []
    for week, batch in log.groupby("week"):
        channel = batch["channel"].value_counts(normalize=True).reindex(list(CHANNELS), fill_value=0).to_dict()
        predicted = batch["predicted_category"].value_counts(normalize=True).to_dict()
        affected_psi = np.mean([psi({"yes": reference["affected"][k], "no": 1 - reference["affected"][k]},
                                    {"yes": batch["affected"].str.contains(k).mean(),
                                     "no": 1 - batch["affected"].str.contains(k).mean()}) for k in AFFECTED])
        row = {"week": int(week), "reports": int(len(batch)),
               "mean_confidence": float(batch["confidence"].mean()),
               "low_confidence_share": float(batch["needs_review"].mean()),
               "agreement": float((batch["predicted_category"] == batch["analyst_category"]).mean()),
               "p95_latency_ms": float(batch["inference_ms"].quantile(0.95)),
               "psi_channel": psi(reference["channel"], channel),
               "psi_affected": float(affected_psi),
               "psi_predicted_category": psi(reference["predicted_category"], predicted)}
        alerts = []
        for name in ("psi_channel", "psi_affected", "psi_predicted_category"):
            if row[name] > THRESHOLDS["psi_alert"]:
                alerts.append(f"{name} {row[name]:.2f} > {THRESHOLDS['psi_alert']} (drift alert)")
            elif row[name] > THRESHOLDS["psi_warning"]:
                alerts.append(f"{name} {row[name]:.2f} > {THRESHOLDS['psi_warning']} (drift warning)")
        if row["agreement"] < THRESHOLDS["agreement_min"]:
            alerts.append(f"agreement {row['agreement']:.0%} < {THRESHOLDS['agreement_min']:.0%} (performance)")
        if row["low_confidence_share"] > THRESHOLDS["low_confidence_max"]:
            alerts.append(f"low-confidence share {row['low_confidence_share']:.0%} > "
                          f"{THRESHOLDS['low_confidence_max']:.0%}")
        if row["p95_latency_ms"] > THRESHOLDS["p95_latency_ms_max"]:
            alerts.append(f"p95 latency {row['p95_latency_ms']:.0f} ms > {THRESHOLDS['p95_latency_ms_max']} ms")
        row["alerts"] = alerts
        row["status"] = "alert" if any("alert" in a or "performance" in a for a in alerts) else (
            "warning" if alerts else "ok")
        weeks.append(row)
    return weeks


def plot(weeks: list[dict]) -> None:
    frame = pd.DataFrame(weeks)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    axes[0].plot(frame["week"], frame["agreement"], marker="o", label="Agreement with analyst", color="#1f9bb0")
    axes[0].plot(frame["week"], frame["mean_confidence"], marker="o", label="Mean confidence", color="#7a7a7a")
    axes[0].axhline(THRESHOLDS["agreement_min"], ls="--", color="#d9344a", lw=1, label="Agreement threshold")
    axes[0].set(ylim=(0, 1.05), xlabel="Week", title="Performance (SIMULATED data)")
    axes[0].legend(fontsize=8, loc="lower left")
    for name, color in (("psi_channel", "#1f9bb0"), ("psi_affected", "#7a7a7a"), ("psi_predicted_category", "#e08a00")):
        axes[1].plot(frame["week"], frame[name], marker="o", label=name.replace("psi_", "PSI "), color=color)
    axes[1].axhline(THRESHOLDS["psi_alert"], ls="--", color="#d9344a", lw=1, label="Alert 0.25")
    axes[1].axhline(THRESHOLDS["psi_warning"], ls=":", color="#e08a00", lw=1, label="Warning 0.10")
    axes[1].set(xlabel="Week", title="Data drift (SIMULATED data)")
    axes[1].legend(fontsize=8, loc="upper left")
    for ax in axes:
        ax.set_xticks(frame["week"])
    fig.tight_layout()
    fig.savefig(OUT_DIR / "monitoring.png", dpi=130)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    load_model()  # warm up so the first latency is not the loading time
    log = simulate(random.Random(SEED))
    log.to_csv(OUT_DIR / "monitoring_log.csv", index=False)
    weeks = weekly_indicators(log, reference)
    plot(weeks)
    report = {"label": "SIMULATED OPERATIONAL DATA - generated by src/monitoring.py for demonstration",
              "generated_utc": datetime.now(timezone.utc).isoformat(), "thresholds": THRESHOLDS,
              "reference_rows": reference["rows"], "weeks": weeks}
    (OUT_DIR / "monitoring_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for week in weeks:
        print(f"[SIMULATED] week {week['week']}: agreement={week['agreement']:.0%} "
              f"confidence={week['mean_confidence']:.0%} psi_channel={week['psi_channel']:.2f} "
              f"psi_category={week['psi_predicted_category']:.2f} status={week['status']} {week['alerts']}")


if __name__ == "__main__":
    main()
