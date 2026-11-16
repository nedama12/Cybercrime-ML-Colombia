"""Train and evaluate independent URL-only phishing classifiers."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

from src.phishing_features import (URL_FEATURE_COLUMNS, make_url_feature_frame,
                                   normalize_url_text, parse_url_host)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data/raw/PhiUSIIL_Phishing_URL_Dataset.csv"
MODEL_PATH = ROOT / "models/phishing_detector.joblib"
INFO_PATH = ROOT / "models/phishing_detector_info.json"
REPORT_DIR = ROOT / "reports/phishing"
RANDOM_STATE = 42


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_clean_rows(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path, usecols=["URL", "Domain", "label"])
    original_rows = len(df)
    missing_selected = int(df.isna().sum().sum())
    source_label_counts = df["label"].value_counts(dropna=False).to_dict()
    df["URL"] = df["URL"].fillna("").astype(str).str.strip()
    df["Domain"] = df["Domain"].fillna("").astype(str).str.strip()
    df["label"] = pd.to_numeric(df["label"], errors="coerce")

    def safe_url_text(value: str) -> str:
        try:
            return normalize_url_text(value) if value else ""
        except ValueError:
            return ""

    df["_url_text"] = df["URL"].map(safe_url_text)
    df["_url_host"] = df["_url_text"].map(parse_url_host)
    df["_domain_host"] = df["Domain"].map(parse_url_host)
    invalid_label = ~df["label"].isin([0, 1])
    url_too_long = df["URL"].str.len() > 2048
    url_parse_failed = (df["_url_host"] == "") & ~url_too_long
    invalid_domain = df["_domain_host"] == ""
    domain_mismatch = ((df["_url_host"] != "") & (df["_domain_host"] != "")
                       & (df["_url_host"] != df["_domain_host"]))
    invalid_url = url_too_long | url_parse_failed
    invalid = invalid_label | invalid_url | invalid_domain | domain_mismatch
    dropped_inconsistent = int(invalid.sum())
    df = df.loc[~invalid].copy()

    duplicate_mask = df["_url_text"].duplicated(keep="first")
    duplicate_rows = int(duplicate_mask.sum())
    conflicting_duplicate_urls = int(
        (df.groupby("_url_text")["label"].nunique() > 1).sum())
    if conflicting_duplicate_urls:
        conflict_urls = (df.groupby("_url_text")["label"].nunique() > 1)
        df = df.loc[~df["_url_text"].isin(conflict_urls[conflict_urls].index)].copy()
        duplicate_mask = df["_url_text"].duplicated(keep="first")
    df = df.loc[~duplicate_mask].copy()

    # The source defines 0=phishing and 1=legitimate; this module uses phishing=1.
    df["target"] = (df["label"] == 0).astype("int8")
    # Treat the conventional www alias and the bare host as one split group.
    df["domain_group"] = df["_url_host"].str.removeprefix("www.")
    details = {
        "source_rows": original_rows,
        "rows_removed_inconsistent": dropped_inconsistent,
        "duplicate_url_rows_removed": duplicate_rows,
        "conflicting_duplicate_urls_removed": conflicting_duplicate_urls,
        "rows_after_cleaning": len(df),
        "missing_values_in_selected_columns": missing_selected,
        "source_label_counts": {str(k): int(v) for k, v in source_label_counts.items()},
        "host_domain_mismatch_rows": int(domain_mismatch.sum()),
        "url_over_max_length_rows": int(url_too_long.sum()),
        "url_parse_failed_rows": int(url_parse_failed.sum()),
        "invalid_domain_rows": int(invalid_domain.sum()),
        "invalid_label_rows": int(invalid_label.sum()),
        "phishing_rows_after_cleaning": int(df["target"].sum()),
        "legitimate_rows_after_cleaning": int((df["target"] == 0).sum()),
    }
    return df.reset_index(drop=True), details


def make_candidates() -> dict[str, Pipeline]:
    vectorizer = lambda: TfidfVectorizer(
        analyzer="char", ngram_range=(3, 5), min_df=2, max_features=120_000,
        dtype=np.float32, lowercase=True, sublinear_tf=True)
    return {
        "char_tfidf_logistic_regression": Pipeline([
            ("features", vectorizer()),
            ("classifier", LogisticRegression(
                C=2.0, class_weight="balanced", solver="liblinear",
                max_iter=500, random_state=RANDOM_STATE)),
        ]),
        "char_tfidf_complement_nb": Pipeline([
            ("features", vectorizer()),
            ("classifier", ComplementNB(alpha=0.2)),
        ]),
        "url_features_logistic_regression": Pipeline([
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(
                C=1.0, class_weight="balanced", max_iter=1000,
                solver="lbfgs", random_state=RANDOM_STATE)),
        ]),
        "url_features_random_forest": Pipeline([
            ("url_features", "passthrough"),
            ("classifier", RandomForestClassifier(
                n_estimators=250, class_weight="balanced_subsample",
                min_samples_leaf=2, max_features="sqrt", n_jobs=-1,
                random_state=RANDOM_STATE)),
        ]),
    }


def as_model_input(model_name: str, urls: pd.Series) -> object:
    if model_name.startswith("url_features_"):
        return make_url_feature_frame(urls)
    return urls.tolist()


def score_predictions(y_true: pd.Series, predicted: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision_phishing": float(precision_score(y_true, predicted, pos_label=1, zero_division=0)),
        "recall_phishing": float(recall_score(y_true, predicted, pos_label=1, zero_division=0)),
        "f1_phishing": float(f1_score(y_true, predicted, pos_label=1, zero_division=0)),
        "f1_macro": float(f1_score(y_true, predicted, average="macro", zero_division=0)),
    }


def split_by_host(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    outer = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=RANDOM_STATE)
    train_idx, remainder_idx = next(
        outer.split(df, y=df["target"], groups=df["domain_group"]))
    train = df.iloc[train_idx]
    remainder = df.iloc[remainder_idx]
    inner = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=RANDOM_STATE + 1)
    val_idx, test_idx = next(inner.split(
        remainder, y=remainder["target"], groups=remainder["domain_group"]))
    splits = {"train": train, "validation": remainder.iloc[val_idx],
              "test": remainder.iloc[test_idx]}
    group_sets = {name: set(part["domain_group"]) for name, part in splits.items()}
    overlaps = {
        "train_validation": len(group_sets["train"] & group_sets["validation"]),
        "train_test": len(group_sets["train"] & group_sets["test"]),
        "validation_test": len(group_sets["validation"] & group_sets["test"]),
    }
    if any(overlaps.values()):
        raise RuntimeError(f"Domain leakage detected in split: {overlaps}")
    for name, part in splits.items():
        if part["target"].nunique() != 2:
            raise ValueError(f"The {name} split does not contain both classes.")
    return splits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA,
                        help="Path to the original PhiUSIIL CSV (defaults to data/raw/).")
    args = parser.parse_args()
    data_path = args.data.expanduser().resolve()
    if not data_path.is_file():
        raise FileNotFoundError(
            f"Dataset not found: {data_path}. Pass the original CSV with --data.")

    started = time.perf_counter()
    df, cleaning = load_clean_rows(data_path)
    splits = split_by_host(df)
    candidate_rows = []
    candidates = make_candidates()
    for name, model in candidates.items():
        start = time.perf_counter()
        train_x = as_model_input(name, splits["train"]["_url_text"])
        validation_x = as_model_input(name, splits["validation"]["_url_text"])
        model.fit(train_x, splits["train"]["target"])
        predicted = model.predict(validation_x)
        candidate_rows.append({"model": name, **score_predictions(
            splits["validation"]["target"], predicted),
            "fit_and_validation_seconds": round(time.perf_counter() - start, 2)})
        print(f"Validation {name}: {candidate_rows[-1]}", flush=True)

    comparison = pd.DataFrame(candidate_rows).sort_values(
        ["f1_phishing", "f1_macro", "recall_phishing"], ascending=False)
    selected_name = str(comparison.iloc[0]["model"])
    selected = candidates[selected_name]

    final_train = pd.concat([splits["train"], splits["validation"]], ignore_index=True)
    selected.fit(as_model_input(selected_name, final_train["_url_text"]),
                 final_train["target"])
    test_x = as_model_input(selected_name, splits["test"]["_url_text"])
    test_y = splits["test"]["target"]
    test_predictions = selected.predict(test_x)
    test_metrics = score_predictions(test_y, test_predictions)
    class_report = classification_report(
        test_y, test_predictions, labels=[0, 1],
        target_names=["legitimate", "phishing"], output_dict=True, zero_division=0)
    matrix = confusion_matrix(test_y, test_predictions, labels=[0, 1])

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(selected, MODEL_PATH, compress=3)
    comparison.to_csv(REPORT_DIR / "validation_model_comparison.csv", index=False)
    pd.DataFrame(class_report).transpose().to_csv(REPORT_DIR / "test_classification_report.csv")
    pd.DataFrame(matrix, index=["actual_legitimate", "actual_phishing"],
                 columns=["predicted_legitimate", "predicted_phishing"]).to_csv(
                     REPORT_DIR / "test_confusion_matrix.csv")

    figure, axis = plt.subplots(figsize=(6, 5))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set(xticks=[0, 1], yticks=[0, 1],
             xticklabels=["Legitimate", "Phishing"],
             yticklabels=["Legitimate", "Phishing"],
             xlabel="Predicted label", ylabel="True label",
             title="Phishing detection — held-out test set")
    for row in range(2):
        for column in range(2):
            axis.text(column, row, str(matrix[row, column]), ha="center", va="center")
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    figure.tight_layout()
    figure.savefig(REPORT_DIR / "test_confusion_matrix.png", dpi=160)
    plt.close(figure)

    host_sets = {name: set(part["domain_group"]) for name, part in splits.items()}
    split_summary = {
        name: {"rows": len(part), "domains": len(host_sets[name]),
               "phishing_rows": int(part["target"].sum()),
               "legitimate_rows": int((part["target"] == 0).sum())}
        for name, part in splits.items()
    }
    info = {
        "model_name": "Phishing Detection",
        "artifact": MODEL_PATH.name,
        "selected_candidate": selected_name,
        "selection_rule": "Highest validation phishing F1, then macro F1, then phishing recall; threshold=0.5.",
        "feature_source": "URL text only; no page is requested, fetched, or executed.",
        "features": URL_FEATURE_COLUMNS if selected_name.startswith("url_features_") else ["URL character n-grams (3-5)"],
        "target": "is_phishing",
        "source_label_mapping": {"0": "phishing", "1": "legitimate"},
        "prediction_label_mapping": {"0": "legitimate", "1": "phishing"},
        "dataset": {"filename": data_path.name, "sha256": sha256_file(data_path), **cleaning},
    "split": {"strategy": "GroupShuffleSplit by normalized URL host (www alias removed)", "seed": RANDOM_STATE,
                  "proportions_requested": {"train": 0.70, "validation": 0.15, "test": 0.15},
                  "actual": split_summary,
                  "overlapping_hosts": {"train_validation": len(host_sets["train"] & host_sets["validation"]),
                                        "train_test": len(host_sets["train"] & host_sets["test"]),
                                        "validation_test": len(host_sets["validation"] & host_sets["test"])}},
        "validation_comparison": comparison.to_dict(orient="records"),
        "test_metrics": test_metrics,
        "test_metrics_by_class": class_report,
        "test_confusion_matrix_labels": ["legitimate", "phishing"],
        "test_confusion_matrix": matrix.tolist(),
        "threshold": 0.5,
        "probabilities_note": "Classifier probability estimates; not calibrated guarantees.",
        "scikit_learn_version": sklearn.__version__,
        "random_state": RANDOM_STATE,
    }
    (INFO_PATH).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORT_DIR / "evaluation.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Selected on validation: {selected_name}", flush=True)
    print(f"Held-out test metrics: {test_metrics}", flush=True)
    print(f"Confusion matrix [legitimate, phishing]:\n{matrix}", flush=True)
    print(f"Training completed in {time.perf_counter() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
