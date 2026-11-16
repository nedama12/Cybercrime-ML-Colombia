"""Before/after evidence of the data cleaning done in analysis/03_cleaning.py.

Compares the raw Attorney General's Office file with crimes_processed.csv and writes
reports/data_quality.json (shown in phase 2 of the app) and reports/data_quality.png.

Usage:  python -m src.data_quality
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
PROCESSED = ROOT / "data/processed/crimes_processed.csv"
OUT_JSON = ROOT / "reports/data_quality.json"
OUT_PNG = ROOT / "reports/data_quality.png"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def main() -> None:
    raw = pd.read_excel(RAW, sheet_name="Data", dtype=str)
    processed = pd.read_csv(PROCESSED)
    no_data = raw.apply(lambda s: s.str.strip().str.upper() == "SIN DATO").sum()
    raw_cases = pd.to_numeric(raw["TOTAL_PROCESOS"], errors="coerce")
    departments_raw = raw["DEPARTAMENTO_HECHO"].str.strip()
    departments_raw = departments_raw[departments_raw.str.upper() != "SIN DATO"]
    q1, q3 = processed["total_cases"].quantile([0.25, 0.75])
    upper_fence = q3 + 1.5 * (q3 - q1)
    outliers = processed[processed["total_cases"] > upper_fence]

    report = {
        "raw": {"rows": int(len(raw)), "columns": int(raw.shape[1]),
                "total_cases": int(raw_cases.sum()),
                "missing_as_sin_dato": {k: int(v) for k, v in no_data.items() if v},
                "exact_duplicates": int(raw.duplicated().sum()),
                "department_spellings": int(departments_raw.nunique()),
                "municipality_spellings": int(raw["MUNICIPIO_HECHO"].str.strip().nunique()),
                "text_with_extra_spaces": int(sum((raw[c].str.strip() != raw[c]).sum() for c in raw.columns))},
        "processed": {"rows": int(len(processed)), "columns": int(processed.shape[1]),
                      "total_cases": int(processed["total_cases"].sum()),
                      "missing": {k: int(v) for k, v in processed.isna().sum().items() if v},
                      "exact_duplicates": int(processed.duplicated().sum()),
                      "departments": int(processed["department_norm"].nunique()),
                      "municipalities": int(processed[["department_norm", "municipality_norm"]]
                                            .drop_duplicates().shape[0]),
                      "partial_year_rows": int(processed["partial_year"].sum()),
                      "categories": processed["category"].value_counts().to_dict()},
        "outliers": {"rule": "total_cases > Q3 + 1.5 x IQR",
                     "q1": float(q1), "q3": float(q3), "upper_fence": float(upper_fence),
                     "rows": int(len(outliers)), "share": float(len(outliers) / len(processed)),
                     "max": int(processed["total_cases"].max()),
                     "top": outliers.nlargest(5, "total_cases")[["department", "report_year", "category",
                                                                "total_cases"]].to_dict("records"),
                     "decision": "Kept: they are real aggregated counts (mainly electronic theft in Bogota), "
                                 "not entry errors. They are only used as weights in statistics."},
        "inconsistencies": {
            "examples": sorted({f"{d} -> {norm(d)}" for d in departments_raw.unique() if d != norm(d)})[:6],
            "decision": "Accents, case and punctuation removed to obtain one spelling per department."},
        "transformations": [
            ["Non-numeric years and counts", "Converted to integers; invalid values become null", "Allows numeric analysis"],
            ["'SIN DATO' (no data)", "Converted to null", "Missing values become explicit"],
            ["Rows without department or municipality (22)", "Dropped", "Location is required for every analysis"],
            ["GRUPO_DELITO, CONSUMADO, PAIS_HECHO", "Dropped", "Constant or empty columns with no information"],
            ["Department and municipality names", "Normalised (no accents, upper case)", "One spelling per place, join with DANE"],
            ["Offense text", "Article extracted (269A-269J, Law 1453 art. 105)", "Basis of the target"],
            ["Article", "Mapped to 9 categories", "Target variable of the benchmark"],
            ["SI/NO, ACTIVO/INACTIVO", "Encoded as 1/0", "Binary features"],
            ["Year 2026", "Flagged with partial_year", "Incomplete year must not distort trends"],
            ["Column names", "Translated to English snake_case", "Consistent naming"],
        ],
    }
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    sin_dato_after = int(processed.astype(str).apply(lambda s: s.str.upper() == "SIN DATO").sum().sum())
    no_location_after = int(processed[["department", "municipality"]].isna().any(axis=1).sum())
    report["processed"]["sin_dato_cells"] = sin_dato_after
    pairs = [("Rows", report["raw"]["rows"], report["processed"]["rows"]),
             ("Cells with 'SIN DATO' text", int(no_data.sum()), sin_dato_after),
             ("Rows without location", int(no_data.get("DEPARTAMENTO_HECHO", 0)), no_location_after)]
    for ax, (title, before, after) in zip(axes, pairs):
        ax.bar(["Before", "After"], [before, after], color=["#9aa4ae", "#39d9e8"])
        ax.set_title(title)
        for i, value in enumerate((before, after)):
            ax.text(i, value, f"{value:,}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("Data cleaning - before and after")
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=130)
    plt.close(fig)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("raw", "processed")}, indent=2, default=str))


if __name__ == "__main__":
    main()
