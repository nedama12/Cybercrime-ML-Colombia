"""Entrena y evalúa clasificadores de categoría de ciberdelito."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/processed/delitos_procesado.csv"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "reports"
CM_DIR = REPORT_DIR / "confusion_matrices"
CLASS_DIR = REPORT_DIR / "classification_reports"
TARGET = "categoria"
# La categoría se construye en Data Engineering desde delito/articulo. Se excluyen
# ambas columnas, sus normalizaciones duplicadas y la magnitud agregada del target.
FEATURES = ["criminalidad", "departamento_hecho", "municipio_hecho", "seccional",
            "ano_hechos", "ano_entrada", "ano_denuncia", "anio_parcial"]
NUMERIC = ["criminalidad", "ano_hechos", "ano_entrada", "ano_denuncia", "anio_parcial"]
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
        raise FileNotFoundError(f"No existe el dataset procesado: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    missing_cols = sorted(set(FEATURES + [TARGET]) - set(df.columns))
    if missing_cols:
        raise ValueError(f"Faltan columnas requeridas en el dataset: {missing_cols}")
    df = df.dropna(subset=[TARGET]).copy()
    X, y = df[FEATURES].copy(), df[TARGET].astype(str)
    counts = y.value_counts()
    if len(counts) < 2 or counts.min() < 2:
        raise ValueError("Se requieren al menos dos clases y dos ejemplos por clase para estratificar.")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y)
    labels = sorted(y.unique())
    print(f"Dataset: {len(df)} filas; entrenamiento={len(X_train)}; prueba={len(X_test)}")
    print(f"Distribución objetivo: {counts.to_dict()}")

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
        cm = confusion_matrix(y_test, pred, labels=labels)
        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=labels,
                    yticklabels=labels, ax=ax)
        ax.set(title=f"Matriz de confusión — {key}", xlabel="Predicción", ylabel="Real")
        plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(CM_DIR / f"{key}.png", dpi=160)
        plt.close(fig)
        (CLASS_DIR / f"{key}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        joblib.dump(pipe, MODEL_DIR / f"{key}.joblib")
        fitted[key] = pipe
        print(f"\n{key}: {metrics}\n{classification_report(y_test, pred, zero_division=0)}")

    results = pd.DataFrame(rows)
    results.to_csv(REPORT_DIR / "model_comparison.csv", index=False)
    # Favorece F1 macro, precision/recall macro y sensibilidad a clases poco frecuentes.
    # Minoritarias: clases con menos del 2% del conjunto completo.
    minority = [c for c, n in counts.items() if n / len(y) < 0.02]
    for row in rows:
        report = reports[row["model"]]
        row["minority_recall"] = sum(report[c]["recall"] for c in minority) / len(minority)
        row["selection_score"] = (0.40 * row["f1_macro"] + 0.20 * row["precision_macro"]
                                  + 0.20 * row["recall_macro"]
                                  + 0.20 * row["minority_recall"])
    results = pd.DataFrame(rows)
    results.to_csv(REPORT_DIR / "model_comparison.csv", index=False)
    best = results.sort_values(["selection_score", "f1_macro"], ascending=False).iloc[0]["model"]
    joblib.dump(fitted[best], MODEL_DIR / "best_model.joblib")
    ax = results.set_index("model")[["accuracy", "precision_macro", "recall_macro",
                                      "f1_macro", "f1_weighted"]].plot(
        kind="bar", figsize=(12, 6), ylim=(0, 1), rot=0)
    ax.set_ylabel("Puntaje")
    ax.set_title("Comparación de modelos en conjunto de prueba")
    ax.legend(loc="lower right")
    ax.figure.tight_layout()
    ax.figure.savefig(REPORT_DIR / "model_comparison.png", dpi=160)
    plt.close(ax.figure)

    info = {
        "algorithm": best, "target": TARGET, "features": FEATURES,
        "parameters": estimators[best].get_params(),
        "metrics": results.set_index("model").loc[best].to_dict(),
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_PATH.relative_to(ROOT)), "dataset_rows": len(df),
        "train_rows": len(X_train), "test_rows": len(X_test), "random_state": 42,
        "class_distribution": {str(k): int(v) for k, v in counts.items()},
        "minority_classes": minority,
        "selection_rule": "0.40*F1 macro + 0.20*precision macro + 0.20*recall macro + 0.20*recall medio clases <2%",
    }
    (MODEL_DIR / "best_model_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nMejor modelo (F1 macro): {best}")
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
