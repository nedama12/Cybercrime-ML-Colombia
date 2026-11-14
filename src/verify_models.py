"""Verifica artefactos existentes y sincroniza el modelo elegido con los reportes."""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.predict import predict_incident

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"


def main():
    comparison = pd.read_csv(REPORTS / "model_comparison.csv")
    with (MODELS / "best_model_info.json").open(encoding="utf-8") as f:
        info = json.load(f)
    class_counts = pd.Series(info["class_distribution"])
    minority = [name for name, count in class_counts.items()
                if int(count) / info["dataset_rows"] < 0.02]
    for index, row in comparison.iterrows():
        with (REPORTS / "classification_reports" / f"{row['model']}.json").open(encoding="utf-8") as f:
            per_class = json.load(f)
        recall = sum(per_class[name]["recall"] for name in minority) / len(minority)
        comparison.loc[index, "minority_recall"] = recall
        comparison.loc[index, "selection_score"] = (
            0.40 * row["f1_macro"] + 0.20 * row["precision_macro"]
            + 0.20 * row["recall_macro"] + 0.20 * recall)
    comparison.to_csv(REPORTS / "model_comparison.csv", index=False)
    best = comparison.sort_values(["selection_score", "f1_macro"], ascending=False).iloc[0]
    best_name = best["model"]
    best_path = MODELS / "best_model.joblib"
    joblib.dump(joblib.load(MODELS / f"{best_name}.joblib"), best_path)
    info.update({"algorithm": best_name,
                 "metrics": {key: (float(value) if hasattr(value, "item") else value)
                             for key, value in best.items() if key != "model"},
                 "minority_classes": minority,
                 "selection_rule": "0.40*F1 macro + 0.20*precision macro + 0.20*recall macro + 0.20*recall medio clases <2%"})
    (MODELS / "best_model_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    for name in ("decision_tree", "random_forest", "logistic_regression", "best_model"):
        model = joblib.load(MODELS / f"{name}.joblib")
        assert hasattr(model, "predict") and hasattr(model, "predict_proba")
    data = pd.read_csv(ROOT / info["dataset"], nrows=1)
    incident = data.iloc[0][info["features"]].to_dict()
    prediction = predict_incident(incident, best_path)
    assert prediction["prediction"]
    assert abs(sum(prediction["probabilities"].values()) - 1.0) < 1e-6
    print(f"Validación correcta: modelos cargados; muestra real -> {prediction['prediction']}")
    print(comparison[["model", "f1_macro", "precision_macro", "recall_macro",
                      "minority_recall", "selection_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
