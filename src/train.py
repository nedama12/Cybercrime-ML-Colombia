"""Location benchmark: can the cybercrime category be predicted from *where* and
*when* a case was registered by the Attorney General's Office?

Trains and compares Decision Tree, Random Forest and Logistic Regression on the
processed Fiscalia dataset. The low scores of this benchmark are the reason the
platform asks citizens to describe what happened (see src/train_report_model.py).

Usage:  python -m src.train
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/processed/crimes_processed.csv"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "reports"
CM_DIR = REPORT_DIR / "confusion_matrices"
CLASS_DIR = REPORT_DIR / "classification_reports"
TARGET = "category"
# The category is built from offense/article during Data Engineering, so both
# columns, their normalised copies and the aggregated count are excluded.
FEATURES = ["criminality", "department", "municipality", "regional_office",
            "offense_year", "entry_year", "report_year", "partial_year"]
NUMERIC = ["criminality", "offense_year", "entry_year", "report_year", "partial_year"]
CATEGORICAL = [c for c in FEATURES if c not in NUMERIC]


def make_pipeline(estimator):
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler(with_mean=False))])
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                            ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    prep = ColumnTransformer([("numeric", numeric, NUMERIC),
                              ("categorical", categorical, CATEGORICAL)])
    return Pipeline([("preprocess", prep), ("classifier", estimator)])


def main():
    for directory in (MODEL_DIR, REPORT_DIR, CM_DIR, CLASS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Processed dataset not found: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    missing_cols = sorted(set(FEATURES + [TARGET]) - set(df.columns))
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    df = df.dropna(subset=[TARGET]).copy()
    X, y = df[FEATURES].copy(), df[TARGET].astype(str)
    counts = y.value_counts()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y)
    labels = sorted(y.unique())
    print(f"Dataset: {len(df)} rows; train={len(X_train)}; test={len(X_test)}")

    estimators = {
        "decision_tree": DecisionTreeClassifier(class_weight="balanced", random_state=42,
                                                 min_samples_leaf=2),
        "random_forest": RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                                random_state=42, n_jobs=-1,
                                                min_samples_leaf=2),
        "logistic_regression": LogisticRegression(max_iter=2000, class_weight="balanced",
                                                  solver="lbfgs", random_state=42),
    }
    rows, reports, fitted = [], {}, {}
    for key, estimator in estimators.items():
        pipe = make_pipeline(estimator)
        pipe.fit(X_train, y_train)
        pred = pipe.predict(X_test)
        metrics = {
            "accuracy": accuracy_score(y_test, pred),
            "precision_macro": precision_score(y_test, pred, average="macro", zero_division=0),
            "recall_macro": recall_score(y_test, pred, average="macro", zero_division=0),
            "f1_macro": f1_score(y_test, pred, average="macro", zero_division=0),
            "f1_weighted": f1_score(y_test, pred, average="weighted", zero_division=0),
            "precision_weighted": precision_score(y_test, pred, average="weighted", zero_division=0),
            "recall_weighted": recall_score(y_test, pred, average="weighted", zero_division=0),
        }
        report = classification_report(y_test, pred, labels=labels, output_dict=True,
                                       zero_division=0)
        reports[key] = report
        rows.append({"model": key, **metrics})
        fig, ax = plt.subplots(figsize=(11, 9))
        ConfusionMatrixDisplay.from_predictions(y_test, pred, labels=labels, ax=ax,
                                                cmap="Blues", colorbar=False,
                                                xticks_rotation=45)
        ax.set(title=f"Confusion matrix - {key}", xlabel="Predicted", ylabel="Actual")
        fig.tight_layout()
        fig.savefig(CM_DIR / f"{key}.png", dpi=140)
        plt.close(fig)
        (CLASS_DIR / f"{key}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        joblib.dump(pipe, MODEL_DIR / f"{key}.joblib")
        fitted[key] = pipe
        print(f"{key}: {metrics}")

    # Favour macro F1, macro precision/recall and recall on rare classes (<2%).
    minority = [c for c, n in counts.items() if n / len(y) < 0.02]
    for row in rows:
        report = reports[row["model"]]
        row["minority_recall"] = sum(report[c]["recall"] for c in minority) / len(minority)
        row["selection_score"] = (0.40 * row["f1_macro"] + 0.20 * row["precision_macro"]
                                  + 0.20 * row["recall_macro"] + 0.20 * row["minority_recall"])
    results = pd.DataFrame(rows)
    results.to_csv(REPORT_DIR / "model_comparison.csv", index=False)
    best = results.sort_values(["selection_score", "f1_macro"], ascending=False).iloc[0]["model"]
    joblib.dump(fitted[best], MODEL_DIR / "best_model.joblib")
    ax = results.set_index("model")[["accuracy", "precision_macro", "recall_macro",
                                      "f1_macro", "f1_weighted"]].plot(
        kind="bar", figsize=(12, 6), ylim=(0, 1), rot=0)
    ax.set_ylabel("Score")
    ax.set_title("Location benchmark - test set comparison")
    ax.legend(loc="upper right")
    ax.figure.tight_layout()
    ax.figure.savefig(REPORT_DIR / "model_comparison.png", dpi=140)
    plt.close(ax.figure)

    info = {
        "name": "Location benchmark",
        "algorithm": best, "target": TARGET, "features": FEATURES,
        "parameters": estimators[best].get_params(),
        "metrics": results.set_index("model").loc[best].to_dict(),
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": DATA_PATH.relative_to(ROOT).as_posix(), "dataset_rows": len(df),
        "train_rows": len(X_train), "test_rows": len(X_test), "random_state": 42,
        "class_distribution": {str(k): int(v) for k, v in counts.items()},
        "minority_classes": minority,
        "selection_rule": "0.40*F1 macro + 0.20*precision macro + 0.20*recall macro "
                          "+ 0.20*mean recall of classes <2%",
    }
    (MODEL_DIR / "best_model_info.json").write_text(
        json.dumps(info, indent=2, default=str), encoding="utf-8")
    print(f"\nSelected benchmark model: {best}")
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
