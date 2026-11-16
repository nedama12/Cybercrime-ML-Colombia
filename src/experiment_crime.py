"""Leakage-aware experiments for the Colombian aggregated crime classifier.

This script writes candidate artifacts and reports to experiment-specific paths.
It never changes the production crime model or the independent phishing module.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score)
from sklearn.feature_selection import SelectPercentile, f_classif
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (OneHotEncoder, OrdinalEncoder, StandardScaler)

from src.crime_features import (CRIME_CATEGORICAL_FEATURES, CRIME_HIST_CATEGORICAL_FEATURES,
                                CRIME_INPUT_FEATURES, CRIME_NUMERIC_FEATURES, CrimeFeatureBuilder)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/processed/delitos_procesado.csv"
EXPERIMENT_DIR = ROOT / "reports/crime_experiments"
CANDIDATE_PATH = ROOT / "models/crime_experiment_candidate.joblib"
CANDIDATE_INFO_PATH = ROOT / "models/crime_experiment_candidate_info.json"
TARGET = "categoria"
RANDOM_STATE = 42
TEST_START_YEAR = 2024
TEMPORAL_VALIDATION_YEAR = 2023
TEMPORAL_TRAIN_END_YEAR = 2022


def category_from_article(article):
    mapping = {
        "269A": "ACCESO_ABUSIVO", "269B": "ATAQUE_A_SISTEMAS",
        "269C": "ATAQUE_A_SISTEMAS", "269D": "ATAQUE_A_SISTEMAS",
        "269E": "MALWARE", "269F": "DATOS_PERSONALES",
        "269G": "PHISHING_SUPLANTACION", "269I": "HURTO_ELECTRONICO",
        "269J": "FRAUDE_TRANSFERENCIA", "L1453": "EQUIPOS_MOVILES",
    }
    return mapping.get(article, "NO_ESPECIFICADO")


def load_data() -> tuple[pd.DataFrame, dict]:
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"Processed crime dataset is missing: {DATA_PATH}")
    frame = pd.read_csv(DATA_PATH)
    missing = sorted(set(CRIME_INPUT_FEATURES + [TARGET]) - set(frame.columns))
    if missing:
        raise ValueError(f"Required crime dataset columns are missing: {missing}")
    frame = frame.loc[frame[TARGET].notna()].copy()
    frame[TARGET] = frame[TARGET].astype(str)
    frame["_crime_geo_group"] = frame[["delito", "departamento_hecho", "municipio_hecho"]].fillna(
        "<MISSING>").astype(str).agg("\x1f".join, axis=1)

    mapped = frame["articulo"].map(category_from_article)
    article_mismatch = int((mapped != frame[TARGET]).sum())
    audit = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns) - 1),
        "target": TARGET,
        "class_distribution": {str(k): int(v) for k, v in frame[TARGET].value_counts().items()},
        "missing_values_by_column": {str(k): int(v) for k, v in
                                     frame.isna().sum()[frame.isna().sum() > 0].items()},
        "missing_values_total": int(frame.isna().sum().sum()),
        "exact_duplicate_rows": int(frame.drop(columns=["_crime_geo_group"]).duplicated().sum()),
        "duplicate_rows_by_crime_department_municipality_year": int(
            frame.duplicated(["delito", "departamento_hecho", "municipio_hecho", "ano_hechos"]).sum()),
        "distinct_crime_department_municipality_groups": int(frame["_crime_geo_group"].nunique()),
        "article_category_mismatches": article_mismatch,
        "article_missing_rows": int(frame["articulo"].isna().sum()),
        "no_specified_rows": int((frame[TARGET] == "NO_ESPECIFICADO").sum()),
        "years": {"min": int(frame["ano_hechos"].min()), "max": int(frame["ano_hechos"].max()),
                  "partial_year_rows": int((frame["anio_parcial"] == 1).sum())},
        "department_count": int(frame["departamento_hecho"].nunique()),
        "municipality_count": int(frame["municipio_hecho"].nunique()),
        "direct_or_indirect_leakage_review": {
            "delito": "Excluded: source text used to derive articulo and categoria.",
            "articulo": "Excluded: deterministic source for category mapping.",
            "es_agravado": "Excluded: derived from delito text.",
            "ley": "Excluded: legal/process metadata may encode source offense or case jurisdiction.",
            "estado_etapa_es_archivo_es_preclusion": "Excluded: post-report case outcomes not available at incident classification time.",
            "total_procesos": "Excluded: aggregate count unavailable for an individual new record and closely tied to aggregation.",
            "departamento_norm_municipio_norm": "Excluded: duplicates of retained place fields.",
            "anio_parcial": "Retained in the input contract for Flask compatibility; dropped from engineered predictors because it is derived from ano_hechos.",
        },
        "label_quality_note": "The target is an approximate legal-article mapping, not an independently adjudicated incident label.",
    }
    return frame.reset_index(drop=True), audit


def original_preprocessor() -> ColumnTransformer:
    numeric = ["criminalidad", "ano_hechos", "ano_entrada", "ano_denuncia", "anio_parcial"]
    categorical = ["departamento_hecho", "municipio_hecho", "seccional"]
    numeric_pipe = Pipeline([("imputer", SimpleImputer(strategy="median")),
                             ("scaler", StandardScaler(with_mean=False))])
    categorical_pipe = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                                 ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    return ColumnTransformer([("numeric", numeric_pipe, numeric),
                              ("categorical", categorical_pipe, categorical)])


def engineered_preprocessor(*, scale_numeric: bool = True) -> ColumnTransformer:
    if scale_numeric:
        numeric_pipe = Pipeline([("imputer", SimpleImputer(strategy="median")),
                                 ("scaler", StandardScaler(with_mean=False))])
    else:
        numeric_pipe = SimpleImputer(strategy="median")
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
    ])
    return ColumnTransformer([
        ("numeric", numeric_pipe, CRIME_NUMERIC_FEATURES),
        ("categorical", categorical_pipe, CRIME_CATEGORICAL_FEATURES),
    ], sparse_threshold=0.3)


def hist_preprocessor() -> ColumnTransformer:
    numeric_pipe = SimpleImputer(strategy="median")
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("ordinal", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
    ])
    return ColumnTransformer([
        ("numeric", numeric_pipe, CRIME_NUMERIC_FEATURES),
        ("categorical", categorical_pipe, CRIME_HIST_CATEGORICAL_FEATURES),
    ], sparse_threshold=0)


def candidate_specs() -> list[dict]:
    return [
        {"name": "original_logistic_regression", "kind": "original_lr",
         "params": {"C": 1.0, "class_weight": "balanced"}},
        {"name": "engineered_logistic_C0.1_balanced", "kind": "engineered_lr",
         "params": {"C": 0.1, "class_weight": "balanced"}},
        {"name": "engineered_logistic_C1_balanced", "kind": "engineered_lr",
         "params": {"C": 1.0, "class_weight": "balanced"}},
        {"name": "engineered_logistic_C1_balanced_select75", "kind": "engineered_lr",
         "params": {"C": 1.0, "class_weight": "balanced"}, "select_percentile": 75},
        {"name": "engineered_logistic_C10_balanced", "kind": "engineered_lr",
         "params": {"C": 10.0, "class_weight": "balanced"}},
        {"name": "engineered_logistic_C1_unweighted", "kind": "engineered_lr",
         "params": {"C": 1.0, "class_weight": None}},
        {"name": "random_forest_balanced", "kind": "random_forest",
         "params": {"n_estimators": 180, "max_features": "sqrt", "min_samples_leaf": 3,
                    "class_weight": "balanced_subsample"}},
        {"name": "extra_trees_balanced", "kind": "extra_trees",
         "params": {"n_estimators": 220, "max_features": "sqrt", "min_samples_leaf": 3,
                    "class_weight": "balanced"}},
        {"name": "hist_gradient_boosting", "kind": "hist_gradient_boosting",
         "params": {"max_iter": 120, "learning_rate": 0.08, "max_leaf_nodes": 15,
                    "l2_regularization": 1.0}},
    ]


def make_pipeline(spec: dict) -> Pipeline:
    params = dict(spec["params"])
    if spec["kind"] == "original_lr":
        classifier = LogisticRegression(max_iter=2000, solver="lbfgs", random_state=RANDOM_STATE,
                                        **params)
        return Pipeline([("preprocess", original_preprocessor()), ("classifier", classifier)])
    if spec["kind"] == "engineered_lr":
        classifier = LogisticRegression(max_iter=6000, tol=1e-3, solver="saga",
                                        random_state=RANDOM_STATE, **params)
        steps = [("feature_builder", CrimeFeatureBuilder()),
                 ("preprocess", engineered_preprocessor())]
        if spec.get("select_percentile"):
            steps.append(("feature_selection", SelectPercentile(
                score_func=f_classif, percentile=spec["select_percentile"])))
        steps.append(("classifier", classifier))
        return Pipeline(steps)
    if spec["kind"] == "random_forest":
        classifier = RandomForestClassifier(n_jobs=-1, random_state=RANDOM_STATE, **params)
        return Pipeline([("feature_builder", CrimeFeatureBuilder()),
                         ("preprocess", engineered_preprocessor(scale_numeric=False)),
                         ("classifier", classifier)])
    if spec["kind"] == "extra_trees":
        classifier = ExtraTreesClassifier(n_jobs=-1, random_state=RANDOM_STATE, **params)
        return Pipeline([("feature_builder", CrimeFeatureBuilder()),
                         ("preprocess", engineered_preprocessor(scale_numeric=False)),
                         ("classifier", classifier)])
    if spec["kind"] == "hist_gradient_boosting":
        cat_start = len(CRIME_NUMERIC_FEATURES)
        categorical_indices = list(range(cat_start, cat_start + len(CRIME_HIST_CATEGORICAL_FEATURES)))
        classifier = HistGradientBoostingClassifier(
            categorical_features=categorical_indices, random_state=RANDOM_STATE, **params)
        return Pipeline([("feature_builder", CrimeFeatureBuilder()),
                         ("preprocess", hist_preprocessor()),
                         ("classifier", classifier)])
    raise ValueError(f"Unknown candidate type: {spec['kind']}")


def model_input(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[CRIME_INPUT_FEATURES].copy()


def metrics(y_true, predicted, labels: list[str]) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision_macro": float(precision_score(y_true, predicted, labels=labels,
                                                  average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, predicted, labels=labels,
                                            average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, predicted, labels=labels,
                                    average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(y_true, predicted, labels=labels,
                                       average="weighted", zero_division=0)),
    }


def class_metrics(y_true, predicted, labels: list[str]) -> dict:
    return classification_report(y_true, predicted, labels=labels, output_dict=True,
                                 zero_division=0)


def fit_and_score(spec: dict, train: pd.DataFrame, test: pd.DataFrame,
                  labels: list[str]) -> tuple[Pipeline, np.ndarray, dict]:
    pipeline = make_pipeline(spec)
    pipeline.fit(model_input(train), train[TARGET])
    predicted = pipeline.predict(model_input(test))
    return pipeline, predicted, metrics(test[TARGET], predicted, labels)


def department_holdout(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    train_idx, test_idx = next(splitter.split(
        frame, frame[TARGET], groups=frame["departamento_hecho"].fillna("<MISSING>")))
    development, test = frame.iloc[train_idx].copy(), frame.iloc[test_idx].copy()
    held_departments = sorted(test["departamento_hecho"].dropna().unique().tolist())
    return development, test, held_departments


def grouped_cv(development: pd.DataFrame, labels: list[str], specs: list[dict]) -> pd.DataFrame:
    splitter = StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE + 1)
    X = model_input(development)
    y = development[TARGET]
    groups = development["_crime_geo_group"]
    fold_rows = []
    for spec in specs:
        for fold, (train_idx, val_idx) in enumerate(splitter.split(X, y, groups=groups), start=1):
            model = make_pipeline(spec)
            model.fit(X.iloc[train_idx], y.iloc[train_idx])
            predicted = model.predict(X.iloc[val_idx])
            fold_metric = metrics(y.iloc[val_idx], predicted, labels)
            classifier = model.named_steps["classifier"]
            n_iter = int(np.max(classifier.n_iter_)) if hasattr(classifier, "n_iter_") else 0
            converged = not hasattr(classifier, "n_iter_") or n_iter < classifier.max_iter
            validation = development.iloc[val_idx]
            minority = [category for category in labels
                        if (development[TARGET] == category).mean() < 0.02]
            class_report = class_metrics(y.iloc[val_idx], predicted, labels)
            fold_metric["minority_recall"] = float(np.mean(
                [class_report[category]["recall"] for category in minority]))
            fold_rows.append({"model": spec["name"], "fold": fold,
                              **fold_metric, "converged": bool(converged),
                              "max_iterations_used": n_iter,
                              "validation_rows": len(validation)})
            print(f"Grouped CV {spec['name']} fold {fold}: "
                  f"macro_f1={fold_metric['f1_macro']:.4f}, "
                  f"minority_recall={fold_metric['minority_recall']:.4f}", flush=True)
    folds = pd.DataFrame(fold_rows)
    summary = folds.groupby("model").agg(
        f1_macro_mean=("f1_macro", "mean"), f1_macro_std=("f1_macro", "std"),
        accuracy_mean=("accuracy", "mean"), precision_macro_mean=("precision_macro", "mean"),
        recall_macro_mean=("recall_macro", "mean"), f1_weighted_mean=("f1_weighted", "mean"),
        minority_recall_mean=("minority_recall", "mean"),
        converged_folds=("converged", "sum"),
    ).reset_index()
    summary["f1_macro_std"] = summary["f1_macro_std"].fillna(0)
    summary = summary.sort_values(["f1_macro_mean", "minority_recall_mean"], ascending=False)
    return folds, summary


def paired_group_bootstrap(y_true, pred_candidate, pred_baseline, groups,
                           labels: list[str], repetitions: int = 400) -> dict:
    group_values = np.asarray(groups)
    unique_groups = np.unique(group_values)
    positions = {group: np.flatnonzero(group_values == group) for group in unique_groups}
    rng = np.random.RandomState(RANDOM_STATE + 7)
    differences = []
    y = np.asarray(y_true)
    candidate = np.asarray(pred_candidate)
    baseline = np.asarray(pred_baseline)
    for _ in range(repetitions):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        indices = np.concatenate([positions[group] for group in sampled])
        f1_new = f1_score(y[indices], candidate[indices], labels=labels,
                          average="macro", zero_division=0)
        f1_old = f1_score(y[indices], baseline[indices], labels=labels,
                          average="macro", zero_division=0)
        differences.append(float(f1_new - f1_old))
    return {
        "repetitions": repetitions,
        "unit": "crime name × department × municipality group",
        "mean_delta_f1_macro": float(np.mean(differences)),
        "ci_95_lower": float(np.quantile(differences, 0.025)),
        "ci_95_upper": float(np.quantile(differences, 0.975)),
    }


def save_evaluation(prefix: str, y_true, predicted, labels: list[str]) -> dict:
    matrix = confusion_matrix(y_true, predicted, labels=labels)
    report = class_metrics(y_true, predicted, labels)
    pd.DataFrame(report).transpose().to_csv(EXPERIMENT_DIR / f"{prefix}_class_metrics.csv")
    pd.DataFrame(matrix, index=labels, columns=labels).to_csv(
        EXPERIMENT_DIR / f"{prefix}_confusion_matrix.csv")
    figure, axis = plt.subplots(figsize=(11, 9))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set(xticks=np.arange(len(labels)), yticks=np.arange(len(labels)),
             xticklabels=labels, yticklabels=labels,
             xlabel="Predicted category", ylabel="Actual category",
             title=prefix.replace("_", " ").title())
    axis.tick_params(axis="x", labelrotation=45)
    threshold = matrix.max() / 2 if matrix.size else 0
    for row in range(len(labels)):
        for column in range(len(labels)):
            axis.text(column, row, f"{matrix[row, column]:,}", ha="center", va="center",
                      color="white" if matrix[row, column] > threshold else "black", fontsize=8)
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    figure.tight_layout()
    figure.savefig(EXPERIMENT_DIR / f"{prefix}_confusion_matrix.png", dpi=150)
    plt.close(figure)
    return {"metrics": metrics(y_true, predicted, labels),
            "by_class": report, "confusion_matrix": matrix.tolist(),
            "confusion_matrix_labels": labels}


def write_markdown(info: dict) -> None:
    lines = [
        "# Cybercrime Classifier Experiment",
        "",
        "This experiment predicts the approximate legal category assigned to aggregated rows. "
        "It is not an individual incident detector.",
        "",
        "## Data audit",
        "",
        f"- Rows: {info['audit']['rows']:,}; exact duplicate rows: {info['audit']['exact_duplicate_rows']:,}.",
        f"- Missing values: {info['audit']['missing_values_total']:,}; target/article mapping mismatches: "
        f"{info['audit']['article_category_mismatches']:,}.",
        f"- CV groups: offense name × department × municipality. Geographic test departments: "
        f"{', '.join(info['geographic_test']['held_departments'])}.",
        "- `delito`, `articulo`, `es_agravado`, aggregate counts, legal/case outcomes, and duplicate "
        "normalized location fields were excluded from predictors.",
        "",
        "## Grouped cross-validation comparison",
        "",
        "| Model | Macro F1 mean | Macro F1 std | Macro precision | Macro recall | Weighted F1 | Minority recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in info["group_cv"]["comparison"]:
        lines.append("| {model} | {f1_macro_mean:.4f} | {f1_macro_std:.4f} | "
                     "{precision_macro_mean:.4f} | {recall_macro_mean:.4f} | "
                     "{f1_weighted_mean:.4f} | {minority_recall_mean:.4f} |".format(**row))
    lines += ["", "## Held-out geographic test", "",
              "| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in info["geographic_test"]["comparison"]:
        m = row["metrics"]
        lines.append(f"| {row['model']} | {m['accuracy']:.4f} | {m['precision_macro']:.4f} | "
                     f"{m['recall_macro']:.4f} | {m['f1_macro']:.4f} | {m['f1_weighted']:.4f} |")
    temporal = info["temporal_test"]
    lines += ["", "## Temporal test", "",
              f"Training years ≤ {TEMPORAL_TRAIN_END_YEAR}; validation year "
              f"{TEMPORAL_VALIDATION_YEAR}; held-out test years ≥ {TEST_START_YEAR}.", "",
              "| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in temporal["comparison"]:
        m = row["metrics"]
        lines.append(f"| {row['model']} | {m['accuracy']:.4f} | {m['precision_macro']:.4f} | "
                     f"{m['recall_macro']:.4f} | {m['f1_macro']:.4f} | {m['f1_weighted']:.4f} |")
    lines += ["", "## Strict spatiotemporal test", "",
              f"Future event years >=2024 within the held-out departments; rows: "
              f"{info['strict_spatiotemporal_test']['rows']:,}.", "",
              "| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, evaluation in ((info["spatial_selected_model"],
                              info["strict_spatiotemporal_test"]["selected_evaluation"]),
                             ("original_logistic_regression",
                              info["strict_spatiotemporal_test"]["original_evaluation"])):
        m = evaluation["metrics"]
        lines.append(f"| {name} | {m['accuracy']:.4f} | {m['precision_macro']:.4f} | "
                     f"{m['recall_macro']:.4f} | {m['f1_macro']:.4f} | {m['f1_weighted']:.4f} |")
    lines += ["", "## Promotion decision", "",
              f"Candidate: `{info['spatial_selected_model']}`. "
              f"Eligible for promotion: **{info['promotion_eligible']}**.", "",
              info["promotion_decision_reason"], "",
              "The historical 80/20 random split reported accuracy 0.1398 and macro F1 0.1176. "
              "That split selected a model using its own test results, so it is retained only as a "
              "legacy reference; comparisons here use independently reserved geography and time.", "",
              "## Limitations", "",
              "The class label is an approximate mapping from legal article to category. Input features "
              "do not describe an incident's technical behavior, so the model cannot identify an "
              "individual cyberattack. The target is strongly tied to crime text, which is deliberately "
              "excluded to avoid direct leakage. Small classes remain statistically unstable, especially "
              "in the strict future-and-unseen-department test.", ""]
    (EXPERIMENT_DIR / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.perf_counter()
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame, audit = load_data()
    labels = sorted(frame[TARGET].unique())
    specs = candidate_specs()
    development_all, geography_test, held_departments = department_holdout(frame)
    development = development_all.loc[development_all["ano_hechos"] <= 2023].copy()
    if development[TARGET].nunique() != len(labels):
        raise ValueError("Development partition is missing one or more target classes.")
    if geography_test[TARGET].nunique() != len(labels):
        raise ValueError("Geographic test partition is missing one or more target classes.")

    folds, cv_summary = grouped_cv(development, labels, specs)
    cv_summary["_complexity"] = cv_summary["model"].map({
        "original_logistic_regression": 0,
        "engineered_logistic_C0.1_balanced": 1,
        "engineered_logistic_C1_balanced": 1,
        "engineered_logistic_C1_balanced_select75": 1,
        "engineered_logistic_C10_balanced": 1,
        "engineered_logistic_C1_unweighted": 1,
        "hist_gradient_boosting": 2,
        "extra_trees_balanced": 3,
        "random_forest_balanced": 4,
    }).fillna(9)
    selected_name = str(cv_summary.sort_values(
        ["f1_macro_mean", "minority_recall_mean", "_complexity"],
        ascending=[False, False, True]).iloc[0]["model"])
    selected_spec = next(spec for spec in specs if spec["name"] == selected_name)

    geo_comparison = []
    geo_predictions = {}
    geo_pipelines = {}
    for spec in specs:
        model, predicted, score = fit_and_score(spec, development, geography_test, labels)
        geo_pipelines[spec["name"]] = model
        geo_predictions[spec["name"]] = predicted
        geo_comparison.append({"model": spec["name"], "metrics": score})
        print(f"Geographic test {spec['name']}: {score}", flush=True)

    baseline_name = "original_logistic_regression"
    selected_geo = geo_predictions[selected_name]
    baseline_geo = geo_predictions[baseline_name]
    selected_geo_metric = next(row["metrics"] for row in geo_comparison
                               if row["model"] == selected_name)
    baseline_geo_metric = next(row["metrics"] for row in geo_comparison
                               if row["model"] == baseline_name)
    geo_bootstrap = paired_group_bootstrap(
        geography_test[TARGET].to_numpy(), selected_geo, baseline_geo,
        geography_test["_crime_geo_group"].to_numpy(), labels)

    temporal_train = frame.loc[frame["ano_hechos"] <= TEMPORAL_TRAIN_END_YEAR].copy()
    temporal_validation = frame.loc[frame["ano_hechos"] == TEMPORAL_VALIDATION_YEAR].copy()
    temporal_test = frame.loc[frame["ano_hechos"] >= TEST_START_YEAR].copy()
    if any(part[TARGET].nunique() != len(labels)
           for part in (temporal_train, temporal_validation, temporal_test)):
        raise ValueError("Temporal split does not contain all nine categories in each partition.")
    temporal_validation_comparison = []
    temporal_specs = {}
    temporal_validation_predictions = {}
    for spec in specs:
        model, predicted, score = fit_and_score(spec, temporal_train, temporal_validation, labels)
        temporal_specs[spec["name"]] = spec
        temporal_validation_predictions[spec["name"]] = predicted
        temporal_validation_comparison.append({"model": spec["name"], "metrics": score})
        print(f"Temporal validation {spec['name']}: {score}", flush=True)
    temporal_selected_name = max(
        temporal_validation_comparison,
        key=lambda row: (row["metrics"]["f1_macro"], row["metrics"]["recall_macro"]))["model"]
    temporal_selected_spec = temporal_specs[temporal_selected_name]
    temporal_test_comparison = []
    temporal_test_predictions = {}
    temporal_test_pipelines = {}
    temporal_refit = pd.concat([temporal_train, temporal_validation], ignore_index=True)
    temporal_eval_specs = []
    for spec in (temporal_selected_spec, selected_spec,
                 next(spec for spec in specs if spec["name"] == baseline_name)):
        if spec["name"] not in {item["name"] for item in temporal_eval_specs}:
            temporal_eval_specs.append(spec)
    for spec in temporal_eval_specs:
        model, predicted, score = fit_and_score(spec, temporal_refit, temporal_test, labels)
        temporal_test_pipelines[spec["name"]] = model
        temporal_test_predictions[spec["name"]] = predicted
        temporal_test_comparison.append({"model": spec["name"], "metrics": score})
        print(f"Temporal test {spec['name']}: {score}", flush=True)

    strict_test = geography_test.loc[geography_test["ano_hechos"] >= TEST_START_YEAR].copy()
    strict_metrics = {}
    strict_predictions = {}
    for spec in (selected_spec, next(spec for spec in specs if spec["name"] == baseline_name)):
        model = geo_pipelines[spec["name"]]
        predicted = model.predict(model_input(strict_test))
        strict_predictions[spec["name"]] = predicted
        strict_metrics[spec["name"]] = metrics(strict_test[TARGET], predicted, labels)

    spatial_selected_temporal_metric = next(
        row["metrics"] for row in temporal_test_comparison if row["model"] == selected_name)
    temporal_baseline_metric = next(
        row["metrics"] for row in temporal_test_comparison if row["model"] == baseline_name)
    minority_classes = [category for category in labels
                        if (frame[TARGET] == category).mean() < 0.02]
    selected_geo_report = class_metrics(geography_test[TARGET], selected_geo, labels)
    baseline_geo_report = class_metrics(geography_test[TARGET], baseline_geo, labels)
    selected_minority_recall = float(np.mean(
        [selected_geo_report[category]["recall"] for category in minority_classes]))
    baseline_minority_recall = float(np.mean(
        [baseline_geo_report[category]["recall"] for category in minority_classes]))
    promotion_conditions = {
        "group_cv_macro_f1_above_original": bool(
            cv_summary.loc[cv_summary.model == selected_name, "f1_macro_mean"].iloc[0]
            > cv_summary.loc[cv_summary.model == baseline_name, "f1_macro_mean"].iloc[0]),
        "held_out_geography_macro_f1_above_original": bool(
            selected_geo_metric["f1_macro"] > baseline_geo_metric["f1_macro"]),
        "group_bootstrap_95pct_delta_lower_above_zero": bool(geo_bootstrap["ci_95_lower"] > 0),
        "minority_recall_no_material_drop": bool(
            selected_minority_recall >= baseline_minority_recall - 0.03),
        "temporal_macro_f1_not_more_than_1pp_below_original": bool(
            spatial_selected_temporal_metric["f1_macro"] >= temporal_baseline_metric["f1_macro"] - 0.01),
    }
    promotion_eligible = bool(all(promotion_conditions.values())
                              and selected_name != baseline_name)
    if promotion_eligible:
        decision_reason = (
            "Candidate clears the predeclared checks: grouped CV and held-out geography improve, "
            "the paired group-bootstrap 95% interval is above zero, minority recall is maintained, "
            "and the temporal holdout is within one F1 point of the original baseline. Candidate "
            "is saved separately and can now be promoted after review.")
    else:
        failed = [name for name, passed in promotion_conditions.items() if not passed]
        if selected_name == baseline_name:
            failed.append("a non-baseline candidate was not selected by grouped CV")
        decision_reason = (
            "Production model was not replaced. Promotion checks not met: " + ", ".join(failed) + ".")

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    folds.to_csv(EXPERIMENT_DIR / "grouped_cv_folds.csv", index=False)
    cv_summary.drop(columns=["_complexity"]).to_csv(
        EXPERIMENT_DIR / "grouped_cv_comparison.csv", index=False)
    temporal_val_frame = pd.DataFrame([
        {"model": row["model"], **row["metrics"]} for row in temporal_validation_comparison])
    temporal_val_frame.to_csv(EXPERIMENT_DIR / "temporal_validation_comparison.csv", index=False)
    (EXPERIMENT_DIR / "geographic_test_comparison.json").write_text(
        json.dumps(geo_comparison, indent=2), encoding="utf-8")
    (EXPERIMENT_DIR / "temporal_test_comparison.json").write_text(
        json.dumps(temporal_test_comparison, indent=2), encoding="utf-8")
    geo_evaluations = {
        name: save_evaluation(f"geographic_{name}", geography_test[TARGET], prediction, labels)
        for name, prediction in geo_predictions.items()
    }
    geo_selected_eval = geo_evaluations[selected_name]
    geo_baseline_eval = geo_evaluations[baseline_name]
    strict_selected_eval = save_evaluation("spatiotemporal_selected", strict_test[TARGET],
                                           strict_predictions[selected_name], labels)
    strict_baseline_eval = save_evaluation("spatiotemporal_original_logistic", strict_test[TARGET],
                                           strict_predictions[baseline_name], labels)
    temporal_selected_eval = save_evaluation(
        "temporal_selected", temporal_test[TARGET],
        temporal_test_predictions[temporal_selected_name], labels)
    temporal_spatial_eval = save_evaluation(
        "temporal_spatial_cv_selected", temporal_test[TARGET],
        temporal_test_predictions[selected_name], labels)
    temporal_baseline_eval = save_evaluation(
        "temporal_original_logistic", temporal_test[TARGET], temporal_test_predictions[baseline_name], labels)

    selected_pipeline = geo_pipelines[selected_name]
    joblib.dump(selected_pipeline, CANDIDATE_PATH, compress=3)
    info = {
        "experiment_date_utc": datetime.now(timezone.utc).isoformat(),
        "scikit_learn_version": sklearn.__version__,
        "dataset_path": str(DATA_PATH.relative_to(ROOT)),
        "audit": audit,
        "historical_original_random_split": {
            "accuracy": 0.1397590361445783, "f1_macro": 0.1176317835506843,
            "note": "Legacy result from a stratified random 80/20 split; it influenced prior model selection and is not an independent estimate.",
        },
        "input_features": CRIME_INPUT_FEATURES,
        "predictor_policy": "Only criminalidad, years, and location are used. No offense text/article, legal outcomes, or aggregate process counts.",
        "feature_engineering": [
            "Reporting and entry delays computed from supplied year fields.",
            "Department-municipality combined location category.",
            "Coarse event-year period computed deterministically inside the pipeline.",
            "OneHotEncoder, imputers, and scalers are fitted within each training fold only.",
        ],
        "oversampling_decision": "Not used: SMOTE is not meaningful for aggregate categorical rows; random duplication could overfit the small classes. Balanced class weights were compared instead.",
        "minority_classes": minority_classes,
        "group_cv": {"strategy": "3-fold StratifiedGroupKFold on offense × department × municipality",
                     "rows": len(development), "groups": int(development["_crime_geo_group"].nunique()),
                     "comparison": cv_summary.drop(columns=["_complexity"]).to_dict(orient="records"),
                     "fold_results": folds.to_dict(orient="records")},
        "spatial_selected_model": selected_name,
        "spatial_selected_parameters": selected_spec,
        "geographic_test": {
            "strategy": "Held-out departments using StratifiedGroupKFold; no department shared with development.",
            "held_departments": held_departments,
            "rows": len(geography_test),
            "development_rows": len(development),
            "no_shared_departments": not bool(set(development.departamento_hecho) & set(geography_test.departamento_hecho)),
            "comparison": geo_comparison,
            "per_model_evaluations": geo_evaluations,
            "selected_evaluation": geo_selected_eval,
            "original_evaluation": geo_baseline_eval,
            "paired_group_bootstrap_vs_original": geo_bootstrap,
        },
        "strict_spatiotemporal_test": {
            "strategy": "Future event years >=2024 within held-out departments; no department overlap with development.",
            "rows": len(strict_test),
            "years": [int(strict_test.ano_hechos.min()), int(strict_test.ano_hechos.max())],
            "selected_evaluation": strict_selected_eval,
            "original_evaluation": strict_baseline_eval,
        },
        "temporal_validation": {
            "train_years": [int(temporal_train.ano_hechos.min()), TEMPORAL_TRAIN_END_YEAR],
            "validation_year": TEMPORAL_VALIDATION_YEAR,
            "comparison": temporal_validation_comparison,
            "selected_model": temporal_selected_name,
        },
        "temporal_test": {
            "strategy": "Train <=2022, validate 2023, refit through 2023, test >=2024.",
            "rows": len(temporal_test),
            "years": [int(temporal_test.ano_hechos.min()), int(temporal_test.ano_hechos.max())],
            "same_crime_geography_groups_across_time": int(
                len(set(temporal_refit._crime_geo_group) & set(temporal_test._crime_geo_group))),
            "comparison": temporal_test_comparison,
            "selected_evaluation": temporal_selected_eval,
            "spatial_cv_selected_evaluation": temporal_spatial_eval,
            "original_evaluation": temporal_baseline_eval,
            "note": "This temporal scenario allows recurring crime-location groups across different event years; the primary promotion test is the department-held-out geography test.",
        },
        "promotion_conditions": promotion_conditions,
        "promotion_eligible": promotion_eligible,
        "promotion_decision_reason": decision_reason,
        "candidate_artifact": str(CANDIDATE_PATH.relative_to(ROOT)),
        "runtime_artifact_unchanged": True,
        "phishing_artifacts_unchanged": True,
        "runtime_model_replaced": False,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    CANDIDATE_INFO_PATH.write_text(json.dumps(info, indent=2, ensure_ascii=False, default=str),
                                   encoding="utf-8")
    (EXPERIMENT_DIR / "evaluation.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_markdown(info)
    print(f"Selected by grouped CV: {selected_name}", flush=True)
    print(f"Geographic test metrics: {selected_geo_metric}", flush=True)
    print(f"Original baseline metrics: {baseline_geo_metric}", flush=True)
    print(f"Temporal selected candidate: {temporal_selected_name}", flush=True)
    print(f"Promotion eligible: {promotion_eligible} — {decision_reason}", flush=True)
    print(f"Experiment completed in {info['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
