"""Train, tune and compare the incident report classifiers.

Protocol (CRISP-ML phases 3 and 4)
1. Split the seed corpus 80/20 with StratifiedGroupKFold grouped by `template_id`,
   so the test phrases never appear in training (no template leakage).
2. Tune Decision Tree, Random Forest and Logistic Regression with GridSearchCV and
   5-fold StratifiedGroupKFold on the training split only (metric: macro F1).
   Every configuration is logged in reports/report_classifier/experiments.csv.
3. Select the algorithm with the best mean cross-validated macro F1.
4. Report final performance on two sets never used for tuning or selection:
   the template-held-out test split and the realistic holdout written separately.

Outputs: models/report_classifier.joblib, models/report_classifier_info.json,
         models/report_reference_stats.json (monitoring baseline),
         reports/report_classifier/ (comparison, experiments, reports, charts)

Usage:  python -m src.train_report_model [--include-confirmed]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             f1_score, precision_score, recall_score, top_k_accuracy_score)
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

from src.report_features import AFFECTED, AFFECTED_COLUMNS, CHANNELS, FEATURES, TEXT_COLUMN, to_frame

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "data/reports/seed_reports.csv"
HOLDOUT_PATH = ROOT / "data/reports/realistic_holdout.csv"
MODEL_PATH = ROOT / "models/report_classifier.joblib"
INFO_PATH = ROOT / "models/report_classifier_info.json"
REFERENCE_PATH = ROOT / "models/report_reference_stats.json"
OUT_DIR = ROOT / "reports/report_classifier"
DB_PATH = Path(os.environ.get("USER_DB_PATH", str(ROOT / "instance/cybercrime.sqlite3")))
RANDOM_STATE = 42
LOW_CONFIDENCE_THRESHOLD = 0.45

CANDIDATES = {
    "decision_tree": (DecisionTreeClassifier(class_weight="balanced", random_state=RANDOM_STATE),
                      {"classifier__max_depth": [None, 30], "classifier__min_samples_leaf": [1, 3, 5]}),
    "random_forest": (RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1,
                                             random_state=RANDOM_STATE),
                      {"classifier__max_depth": [None, 40], "classifier__min_samples_leaf": [1, 2]}),
    "logistic_regression": (LogisticRegression(max_iter=3000, class_weight="balanced",
                                               random_state=RANDOM_STATE),
                            {"classifier__C": [0.5, 2.0, 8.0, 32.0]}),
}


def make_pipeline(estimator) -> Pipeline:
    text = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True,
                                  strip_accents="unicode", lowercase=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                                  sublinear_tf=True, strip_accents="unicode", lowercase=True,
                                  max_features=20000)),
    ])
    prep = ColumnTransformer([
        ("text", text, TEXT_COLUMN),
        ("channel", OneHotEncoder(handle_unknown="ignore"), ["channel"]),
        ("affected", "passthrough", AFFECTED_COLUMNS),
    ])
    return Pipeline([("preprocess", prep), ("classifier", estimator)])


def load_confirmed() -> pd.DataFrame:
    """Reports whose category was confirmed by an analyst become training data."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as connection:
        try:
            frame = pd.read_sql_query(
                "SELECT id, description, channel, affected, confirmed_category AS category "
                "FROM incident_reports WHERE confirmed_category IS NOT NULL", connection)
        except (sqlite3.Error, pd.errors.DatabaseError):
            return pd.DataFrame()
    frame["template_id"] = "confirmed:" + frame.pop("id").astype(str)
    frame["source"] = "confirmed"
    return frame


def evaluate(pipe, X, y, labels) -> tuple[dict, dict, np.ndarray]:
    pred = pipe.predict(X)
    proba = pipe.predict_proba(X)
    confidence = proba.max(axis=1)
    confident = confidence >= LOW_CONFIDENCE_THRESHOLD
    metrics = {
        "accuracy": accuracy_score(y, pred),
        "precision_macro": precision_score(y, pred, average="macro", zero_division=0),
        "recall_macro": recall_score(y, pred, average="macro", zero_division=0),
        "f1_macro": f1_score(y, pred, average="macro", zero_division=0),
        "top2_accuracy": top_k_accuracy_score(y, proba, k=2, labels=pipe.classes_),
        "mean_confidence": float(confidence.mean()),
        "coverage_above_threshold": float(confident.mean()),
        "accuracy_above_threshold": float((pred[confident] == np.asarray(y)[confident]).mean())
        if confident.any() else 0.0,
    }
    report = classification_report(y, pred, labels=labels, output_dict=True, zero_division=0)
    return metrics, report, pred


def reference_stats(X: pd.DataFrame, pipe, labels) -> dict:
    """Baseline distributions used by src/monitoring.py to detect drift."""
    predicted = pd.Series(pipe.predict(X)).value_counts(normalize=True)
    return {
        "channel": X["channel"].value_counts(normalize=True).reindex(list(CHANNELS), fill_value=0).to_dict(),
        "affected": {key: float(X[f"affected_{key}"].mean()) for key in AFFECTED},
        "predicted_category": predicted.reindex(labels, fill_value=0).to_dict(),
        "description_length_mean": float(X[TEXT_COLUMN].str.len().mean()),
        "mean_confidence": float(pipe.predict_proba(X).max(axis=1).mean()),
        "rows": int(len(X)),
    }


def plot_cv(results: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    names = results["model"].str.replace("_", " ").str.title()
    x = np.arange(len(results))
    ax.bar(x - 0.27, results["train_f1_macro"], 0.27, label="Training", color="#9aa4ae")
    ax.bar(x, results["cv_f1_macro_mean"], 0.27, yerr=results["cv_f1_macro_std"], capsize=4,
           label="Cross-validation (5 folds)", color="#39d9e8")
    ax.bar(x + 0.27, results["test_f1_macro"], 0.27, label="Independent test", color="#ff596b")
    ax.set_xticks(x, names)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Macro F1")
    ax.set_title("Report classifier - training vs cross-validation vs test")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "cv_comparison.png", dpi=130)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-confirmed", action="store_true",
                        help="add analyst-confirmed reports from the platform database")
    args = parser.parse_args()

    data = pd.read_csv(SEED_PATH, keep_default_na=False)
    if args.include_confirmed:
        confirmed = load_confirmed()
        print(f"Confirmed reports added: {len(confirmed)}")
        data = pd.concat([data, confirmed], ignore_index=True)
    holdout = pd.read_csv(HOLDOUT_PATH, keep_default_na=False)

    X, y, groups = to_frame(data.to_dict("records")), data["category"].astype(str), data["template_id"]
    X_hold, y_hold = to_frame(holdout.to_dict("records")), holdout["category"].astype(str)
    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    train_idx, test_idx = next(outer.split(X, y, groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    g_train = groups.iloc[train_idx]
    assert not set(g_train) & set(groups.iloc[test_idx]), "template leakage between train and test"
    labels = sorted(y.unique())
    print(f"Train rows={len(X_train)} ({g_train.nunique()} templates) | "
          f"test rows={len(X_test)} ({groups.iloc[test_idx].nunique()} unseen templates) | "
          f"realistic holdout rows={len(X_hold)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "classification_reports").mkdir(exist_ok=True)
    (OUT_DIR / "confusion_matrices").mkdir(exist_ok=True)

    inner = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    rows, experiments, fitted = [], [], {}
    for key, (estimator, grid) in CANDIDATES.items():
        search = GridSearchCV(make_pipeline(estimator), grid, cv=inner, n_jobs=1,
                              scoring={"f1_macro": "f1_macro", "accuracy": "accuracy"},
                              refit="f1_macro", return_train_score=True)
        search.fit(X_train, y_train, groups=g_train)
        cv = pd.DataFrame(search.cv_results_)
        for _, run in cv.iterrows():
            experiments.append({
                "model": key,
                "params": json.dumps({k.replace("classifier__", ""): v for k, v in run["params"].items()}),
                "cv_f1_macro_mean": run["mean_test_f1_macro"], "cv_f1_macro_std": run["std_test_f1_macro"],
                "cv_accuracy_mean": run["mean_test_accuracy"], "train_f1_macro_mean": run["mean_train_f1_macro"],
                "fit_seconds": run["mean_fit_time"], "rank": int(run["rank_test_f1_macro"])})
        best = search.best_estimator_
        best_run = cv.loc[search.best_index_]
        train_metrics, _, _ = evaluate(best, X_train, y_train, labels)
        test_metrics, test_report, _ = evaluate(best, X_test, y_test, labels)
        hold_metrics, hold_report, hold_pred = evaluate(best, X_hold, y_hold, labels)
        rows.append({
            "model": key,
            "best_params": json.dumps({k.replace("classifier__", ""): v for k, v in search.best_params_.items()}),
            "cv_f1_macro_mean": best_run["mean_test_f1_macro"], "cv_f1_macro_std": best_run["std_test_f1_macro"],
            "cv_accuracy_mean": best_run["mean_test_accuracy"],
            "train_f1_macro": train_metrics["f1_macro"],
            **{f"test_{k}": v for k, v in test_metrics.items()},
            **{f"holdout_{k}": v for k, v in hold_metrics.items()},
        })
        (OUT_DIR / "classification_reports" / f"{key}.json").write_text(
            json.dumps({"test": test_report, "holdout": hold_report}, indent=2), encoding="utf-8")
        fig, ax = plt.subplots(figsize=(9, 8))
        ConfusionMatrixDisplay.from_predictions(y_hold, hold_pred, labels=labels, ax=ax, cmap="Blues",
                                                colorbar=False, xticks_rotation=45)
        ax.set(title=f"Realistic holdout - {key}", xlabel="Predicted", ylabel="Actual")
        fig.tight_layout()
        fig.savefig(OUT_DIR / "confusion_matrices" / f"{key}.png", dpi=130)
        plt.close(fig)
        fitted[key] = best
        print(f"{key}: best {search.best_params_} | CV F1={best_run['mean_test_f1_macro']:.3f}"
              f"±{best_run['std_test_f1_macro']:.3f} | train F1={train_metrics['f1_macro']:.3f} | "
              f"test F1={test_metrics['f1_macro']:.3f} | holdout acc={hold_metrics['accuracy']:.3f}")

    results = pd.DataFrame(rows)
    results.to_csv(OUT_DIR / "model_comparison.csv", index=False)
    pd.DataFrame(experiments).sort_values(["model", "rank"]).to_csv(OUT_DIR / "experiments.csv", index=False)
    plot_cv(results)
    best = results.sort_values(["cv_f1_macro_mean", "cv_accuracy_mean"], ascending=False).iloc[0]
    model = fitted[best["model"]]
    joblib.dump(model, MODEL_PATH)
    REFERENCE_PATH.write_text(json.dumps(reference_stats(X_train, model, labels), indent=2), encoding="utf-8")

    info = {
        "name": "Incident report classifier",
        "version": datetime.now(timezone.utc).strftime("%Y.%m.%d"),
        "algorithm": best["model"],
        "best_params": json.loads(best["best_params"]),
        "target": "category",
        "features": FEATURES,
        "labels": labels,
        "metrics": {k: float(v) for k, v in best.items() if k not in ("model", "best_params")},
        "selection_rule": "Highest mean macro F1 in 5-fold StratifiedGroupKFold cross-validation "
                          "(grouped by template) on the training split",
        "validation": "Hyper-parameters tuned with GridSearchCV on the training split only; the "
                      "template-held-out test split and the realistic holdout were not used for "
                      "tuning or selection",
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        "holdout_rows": int(len(X_hold)), "templates": int(groups.nunique()),
        "sources": data["source"].value_counts().to_dict(),
        "random_state": RANDOM_STATE,
    }
    INFO_PATH.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"\nSelected: {best['model']} {best['best_params']}")
    print(results[["model", "cv_f1_macro_mean", "cv_f1_macro_std", "train_f1_macro", "test_f1_macro",
                   "test_accuracy", "holdout_accuracy", "holdout_f1_macro", "holdout_mean_confidence"]]
          .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
