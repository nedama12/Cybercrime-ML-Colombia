"""Territorial and temporal analysis for aggregated Colombian cybercrime records.

The module reports process counts and population rates. It does not classify
individual incidents or claim that reported cases equal actual prevalence.
"""
from __future__ import annotations

from base64 import b64encode
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
CRIME_PATH = ROOT / "data/processed/delitos_procesado.csv"
RAW_CRIME_PATH = ROOT / "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
RAW_POPULATION_PATH = ROOT / "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"
MUNICIPAL_RATE_PATH = ROOT / "data/processed/rates_municipality_year.csv"
DEPARTMENT_RATE_PATH = ROOT / "data/processed/rates_department_year.csv"
PARTIAL_YEAR = 2026
LAST_COMPLETE_YEAR = 2025
FORECAST_YEARS = (2027, 2028, 2029)

CATEGORY_LABELS = {
    "ACCESO_ABUSIVO": "Unauthorized system access (Article 269A)",
    "ATAQUE_A_SISTEMAS": "System obstruction, interception, or damage (Articles 269B–269D)",
    "DATOS_PERSONALES": "Personal data violation (Article 269F)",
    "EQUIPOS_MOVILES": "Mobile terminal manipulation (Article 105, Law 1453)",
    "FRAUDE_TRANSFERENCIA": "Non-consensual asset transfer (Article 269J)",
    "HURTO_ELECTRONICO": "Computer-related theft (Article 269I)",
    "MALWARE": "Malicious software (Article 269E)",
    "PHISHING_SUPLANTACION": "Website impersonation (Article 269G)",
}
LEGAL_CATEGORIES = tuple(CATEGORY_LABELS)
YEAR_FIELDS = {"report": "ano_denuncia", "event": "ano_hechos"}


@lru_cache(maxsize=1)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not CRIME_PATH.exists():
        raise FileNotFoundError(f"Crime dataset not found: {CRIME_PATH}")
    crimes = pd.read_csv(CRIME_PATH, encoding="utf-8-sig", low_memory=False)
    required = {"categoria", "total_procesos", "departamento_hecho", "municipio_hecho",
                "ano_hechos", "ano_denuncia"}
    missing = sorted(required - set(crimes.columns))
    if missing:
        raise ValueError(f"Crime dataset is missing required columns: {missing}")
    crimes = crimes.copy()
    for col in ("ano_hechos", "ano_denuncia", "total_procesos"):
        crimes[col] = pd.to_numeric(crimes[col], errors="coerce")
    crimes["categoria"] = crimes["categoria"].fillna("NO_ESPECIFICADO").astype(str)
    crimes["_dep_key"] = crimes["departamento_hecho"].map(normalize_location)
    crimes["_mun_key"] = crimes["municipio_hecho"].map(normalize_location)
    crimes = crimes[crimes["total_procesos"].notna() & (crimes["total_procesos"] >= 0)]

    municipal_rates = read_rate_file(MUNICIPAL_RATE_PATH,
                                     {"department_norm", "municipality_norm", "report_year",
                                      "population", "total_cases", "rate_100k"})
    department_rates = read_rate_file(DEPARTMENT_RATE_PATH,
                                      {"department_norm", "report_year", "population",
                                       "total_cases", "rate_100k"})
    if not municipal_rates.empty:
        municipal_rates["_dep_key"] = municipal_rates["department_norm"].map(normalize_location)
        municipal_rates["_mun_key"] = municipal_rates["municipality_norm"].map(normalize_location)
        municipal_rates["report_year"] = pd.to_numeric(municipal_rates["report_year"], errors="coerce")
        municipal_rates["population"] = pd.to_numeric(municipal_rates["population"], errors="coerce")
        municipal_rates["total_cases"] = pd.to_numeric(municipal_rates["total_cases"], errors="coerce")
        municipal_rates = municipal_rates.dropna(subset=["report_year", "population"])
    if not department_rates.empty:
        department_rates["_dep_key"] = department_rates["department_norm"].map(normalize_location)
        department_rates["report_year"] = pd.to_numeric(department_rates["report_year"], errors="coerce")
        department_rates["population"] = pd.to_numeric(department_rates["population"], errors="coerce")
        department_rates["total_cases"] = pd.to_numeric(department_rates["total_cases"], errors="coerce")
        department_rates = department_rates.dropna(subset=["report_year", "population"])
    return crimes, municipal_rates, department_rates


def normalize_location(value) -> str:
    if pd.isna(value):
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().upper()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value).split())


def read_rate_file(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    return frame


@lru_cache(maxsize=1)
def inspect_original_sources() -> dict:
    """Read workbook headers and row count without changing the source file."""
    if not RAW_CRIME_PATH.exists():
        return {"crime_workbook_available": False, "crime_source_rows": None,
                "crime_source_columns": [],
                "population_workbook_available": RAW_POPULATION_PATH.exists()}
    workbook = load_workbook(RAW_CRIME_PATH, read_only=True, data_only=True)
    try:
        if "Data" not in workbook.sheetnames:
            return {"crime_workbook_available": True, "crime_source_rows": None,
                    "crime_source_columns": [],
                    "population_workbook_available": RAW_POPULATION_PATH.exists()}
        sheet = workbook["Data"]
        values = sheet.iter_rows(min_row=1, max_row=1, values_only=True)
        columns = list(next(values, ()))
        row_count = sum(1 for row in sheet.iter_rows(min_row=2, values_only=True)
                        if any(value is not None for value in row))
    finally:
        workbook.close()
    return {"crime_workbook_available": True, "crime_source_rows": row_count,
            "crime_source_columns": [str(value) for value in columns if value is not None],
            "population_workbook_available": RAW_POPULATION_PATH.exists()}


def _filtered_crimes(filters: dict, year_basis: str | None = None) -> pd.DataFrame:
    crimes, _, _ = load_data()
    data = crimes[crimes["categoria"].isin(LEGAL_CATEGORIES)].copy()
    scope = filters.get("scope", "national")
    department = filters.get("department", "")
    municipality = filters.get("municipality", "")
    if scope in {"department", "municipality"} and department:
        data = data[data["departamento_hecho"].astype(str) == department]
    if scope == "municipality" and municipality:
        data = data[data["municipio_hecho"].astype(str) == municipality]
    category = filters.get("category", "all")
    if category in LEGAL_CATEGORIES:
        data = data[data["categoria"] == category]
    if year_basis:
        field = YEAR_FIELDS[year_basis]
        data = data[data[field].notna()].copy()
        data[field] = data[field].astype(int)
    return data


def _population_for_series(data: pd.DataFrame, basis: str, scope: str,
                           department: str, municipality: str) -> pd.DataFrame:
    """Join rates only on exact normalized place keys and the same report year."""
    _, municipal_rates, department_rates = load_data()
    if basis != "report" or data.empty:
        return pd.DataFrame(columns=["year", "population"])
    if scope == "municipality" and municipality:
        if municipal_rates.empty:
            return pd.DataFrame(columns=["year", "population"])
        key_dep, key_mun = normalize_location(department), normalize_location(municipality)
        rows = municipal_rates[(municipal_rates["_dep_key"] == key_dep)
                               & (municipal_rates["_mun_key"] == key_mun)]
        return rows[["report_year", "population"]].rename(columns={"report_year": "year"})
    if scope == "department" and department:
        if department_rates.empty:
            return pd.DataFrame(columns=["year", "population"])
        rows = department_rates[department_rates["_dep_key"] == normalize_location(department)]
        return rows[["report_year", "population"]].rename(columns={"report_year": "year"})
    if department_rates.empty:
        return pd.DataFrame(columns=["year", "population"])
    national = department_rates.groupby("report_year", as_index=False)["population"].sum()
    return national.rename(columns={"report_year": "year"})


def _series_for(data: pd.DataFrame, basis: str, filters: dict) -> pd.DataFrame:
    year_field = YEAR_FIELDS[basis]
    selected_scope = filters.get("scope", "national")
    if selected_scope == "municipality" and filters.get("municipality"):
        scope = "municipality"
    elif selected_scope == "department" and filters.get("department"):
        scope = "department"
    else:
        scope = "national"
    if data.empty:
        return pd.DataFrame(columns=["year", "processes", "population", "rate_100k"])
    selected = data.groupby(year_field, as_index=False)["total_procesos"].sum()
    selected = selected.rename(columns={year_field: "year", "total_procesos": "processes"})
    selected["year"] = selected["year"].astype(int)
    populations = _population_for_series(data, basis, scope,
                                          filters.get("department", ""),
                                          filters.get("municipality", ""))
    if not populations.empty:
        selected = selected.merge(populations, how="left", on="year", validate="one_to_one")
        selected["rate_100k"] = np.where(
            selected["population"].gt(0), selected["processes"] / selected["population"] * 100_000,
            np.nan)
    else:
        selected["population"] = np.nan
        selected["rate_100k"] = np.nan
    return selected.sort_values("year")


def _comparison_table(filters: dict, basis: str, selected_year: int) -> list[dict]:
    comparison_filters = dict(filters)
    if filters.get("compare_level") == "department":
        comparison_filters.update(scope="national", department="", municipality="")
    else:
        comparison_filters.update(scope="department", municipality="")
    data = _filtered_crimes(comparison_filters, basis)
    year_field = YEAR_FIELDS[basis]
    data = data[data[year_field] == selected_year]
    level = filters.get("compare_level", "department")
    if level == "municipality":
        if filters.get("department"):
            data = data[data["departamento_hecho"].astype(str) == filters["department"]]
        group_fields = ["departamento_hecho", "municipio_hecho"]
    else:
        group_fields = ["departamento_hecho"]
    rows = data.groupby(group_fields, dropna=False)["total_procesos"].sum().reset_index()

    # Population denominators are only available for report years in processed tables.
    # These tables cover the seven major categories; rate numerators below are rebuilt
    # from the selected legal-category records and joined to the stored denominator.
    if basis == "report":
        _, municipal_rates, department_rates = load_data()
        if level == "department" and not department_rates.empty:
            pops = department_rates[department_rates["report_year"] == selected_year][
                ["_dep_key", "population"]].drop_duplicates("_dep_key")
            rows["_dep_key"] = rows["departamento_hecho"].map(normalize_location)
            rows = rows.merge(pops, how="left", on="_dep_key", validate="many_to_one")
        elif level == "municipality" and not municipal_rates.empty:
            pops = municipal_rates[municipal_rates["report_year"] == selected_year][
                ["_dep_key", "_mun_key", "population"]].drop_duplicates(["_dep_key", "_mun_key"])
            rows["_dep_key"] = rows["departamento_hecho"].map(normalize_location)
            rows["_mun_key"] = rows["municipio_hecho"].map(normalize_location)
            rows = rows.merge(pops, how="left", on=["_dep_key", "_mun_key"], validate="many_to_one")
        else:
            rows["population"] = np.nan
        rows["rate_100k"] = np.where(rows["population"].gt(0),
                                     rows["total_procesos"] / rows["population"] * 100_000,
                                     np.nan)
    else:
        rows["population"] = np.nan
        rows["rate_100k"] = np.nan

    ranking_metric = "rate_100k" if basis == "report" and rows["rate_100k"].notna().any() else "total_procesos"
    rows = rows.sort_values(ranking_metric, ascending=False, na_position="last").head(12)

    result = []
    for _, row in rows.iterrows():
        place = str(row["departamento_hecho"])
        if level == "municipality":
            place = f"{row['municipio_hecho']}, {place}"
        rate = row.get("rate_100k")
        population = row.get("population")
        result.append({"place": place, "processes": int(row["total_procesos"]),
                       "population": int(population) if pd.notna(population) else None,
                       "rate_100k": float(rate) if pd.notna(rate) else None})
    return result


def _trend_chart(series: pd.DataFrame, basis: str, show_rate: bool) -> str | None:
    if series.empty:
        return None
    fig, axis = plt.subplots(figsize=(8.5, 3.4), dpi=110)
    col = "rate_100k" if show_rate and series["rate_100k"].notna().any() else "processes"
    label = "Processes per 100,000 residents" if col == "rate_100k" else "Reported processes"
    axis.plot(series["year"], series[col], color="#16836b", marker="o", linewidth=2)
    axis.set_xlabel("Report year" if basis == "report" else "Event year")
    axis.set_ylabel(label)
    axis.grid(axis="y", alpha=.2)
    fig.tight_layout()
    return _figure_data_uri(fig)


def _category_chart(data: pd.DataFrame, basis: str) -> str | None:
    if data.empty:
        return None
    year_field = YEAR_FIELDS[basis]
    table = data.groupby([year_field, "categoria"])["total_procesos"].sum().unstack(fill_value=0)
    if table.empty:
        return None
    fig, axis = plt.subplots(figsize=(8.5, 3.8), dpi=110)
    for category in LEGAL_CATEGORIES:
        if category in table:
            axis.plot(table.index, table[category], marker="o", linewidth=1.5,
                      label=CATEGORY_LABELS[category])
    axis.set_xlabel("Report year" if basis == "report" else "Event year")
    axis.set_ylabel("Reported processes")
    axis.grid(axis="y", alpha=.2)
    axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7, frameon=False)
    fig.tight_layout()
    return _figure_data_uri(fig)


def _comparison_chart(rows: list[dict], metric: str) -> str | None:
    if not rows:
        return None
    if metric != "processes":
        rows_with_rate = [row for row in rows if row.get(metric) is not None]
        if rows_with_rate:
            rows = rows_with_rate
        else:
            metric = "processes"
    rows = list(reversed(rows))
    values = [row.get(metric) for row in rows]
    if not any(value is not None for value in values):
        metric = "processes"
        values = [row[metric] for row in rows]
    fig, axis = plt.subplots(figsize=(8.5, max(3.2, len(rows) * .28)), dpi=110)
    axis.barh([row["place"] for row in rows], values, color="#16836b")
    axis.set_xlabel("Processes per 100,000 residents" if metric == "rate_100k" else "Reported processes")
    axis.grid(axis="x", alpha=.2)
    fig.tight_layout()
    return _figure_data_uri(fig)


def _figure_data_uri(fig) -> str:
    output = BytesIO()
    fig.savefig(output, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + b64encode(output.getvalue()).decode("ascii")


def _predict_value(history: pd.Series, year: int, model_name: str) -> float:
    history = history.sort_index().astype(float)
    if model_name == "three_year_mean":
        return max(0.0, float(history.tail(3).mean()))
    x = history.index.to_numpy(dtype=float)
    y = history.to_numpy(dtype=float)
    if len(x) < 2:
        return max(0.0, float(y[-1]))
    slope, intercept = np.polyfit(x, y, 1)
    return max(0.0, float(slope * year + intercept))


def _forecast(data: pd.DataFrame, basis: str) -> dict | None:
    if data.empty:
        return None
    year_field = YEAR_FIELDS[basis]
    training = data[(data[year_field] <= LAST_COMPLETE_YEAR) & data[year_field].notna()]
    annual = training.groupby(year_field)["total_procesos"].sum().sort_index()
    if len(annual) < 8:
        return {"available": False, "reason": "At least eight complete annual observations are required for a forecast."}
    years = np.arange(int(annual.index.min()), LAST_COMPLETE_YEAR + 1)
    annual = annual.reindex(years, fill_value=0)
    validation_years = [year for year in (2023, 2024, 2025)
                        if year in annual.index and (annual.loc[:year - 1] > 0).sum() >= 5]
    if len(validation_years) < 2:
        return {"available": False, "reason": "Too few historical observations to compare forecast methods reliably."}
    model_names = ("three_year_mean", "linear_trend")
    scores = {}
    backtests = []
    for model_name in model_names:
        errors = []
        for year in validation_years:
            history = annual.loc[annual.index < year]
            predicted = _predict_value(history, year, model_name)
            actual = float(annual.loc[year])
            errors.append(abs(actual - predicted))
            backtests.append({"year": int(year), "model": model_name,
                              "observed": actual, "predicted": predicted})
        scores[model_name] = float(np.mean(errors))
    selected = min(scores, key=scores.get)
    future = [{"year": year, "forecast": _predict_value(annual, year, selected)}
              for year in FORECAST_YEARS]
    return {"available": True, "model": selected, "mae": scores[selected],
            "scores": scores, "validation_years": validation_years,
            "backtests": backtests, "future": future,
            "trained_through": LAST_COMPLETE_YEAR,
            "note": ("The source marks 2026 as partial, so it is excluded from training. "
                     "Forecasts begin in 2027 and are exploratory annual process-volume estimates.")}


def _forecast_chart(series: pd.DataFrame, forecast: dict | None) -> str | None:
    if forecast is None or not forecast.get("available"):
        return None
    observed = series[(series["year"] <= LAST_COMPLETE_YEAR)]
    future = forecast["future"]
    fig, axis = plt.subplots(figsize=(8.5, 3.4), dpi=110)
    axis.plot(observed["year"], observed["processes"], color="#16836b", marker="o",
              linewidth=1.8, label="Observed")
    backtest = [row for row in forecast["backtests"] if row["model"] == forecast["model"]]
    if backtest:
        axis.plot([row["year"] for row in backtest], [row["predicted"] for row in backtest],
                  color="#bf5c4b", marker="x", linestyle=":", linewidth=1.6,
                  label="Backtest forecast")
    axis.plot([row["year"] for row in future], [row["forecast"] for row in future],
              color="#bf5c4b", marker="o", linestyle="--", linewidth=1.8,
              label=f"Forecast · {forecast['model'].replace('_', ' ')}")
    axis.set_xlabel("Year")
    axis.set_ylabel("Reported processes")
    axis.grid(axis="y", alpha=.2)
    axis.legend(frameon=False)
    fig.tight_layout()
    return _figure_data_uri(fig)


def build_analysis_context(filters: dict) -> dict:
    crimes, municipal_rates, department_rates = load_data()
    departments = sorted(crimes["departamento_hecho"].dropna().astype(str).unique())
    selected_department = filters.get("department", "")
    if selected_department not in departments:
        selected_department = ""
    municipalities = sorted(crimes.loc[
        crimes["departamento_hecho"].astype(str) == selected_department,
        "municipio_hecho"].dropna().astype(str).unique()) if selected_department else []
    selected_municipality = filters.get("municipality", "")
    if selected_municipality not in municipalities:
        selected_municipality = ""
    scope = filters.get("scope", "national")
    if scope not in {"national", "department", "municipality"}:
        scope = "national"
    if scope == "municipality" and not selected_municipality:
        scope = "department" if selected_department else "national"
    if scope == "department" and not selected_department:
        scope = "national"
    basis = filters.get("basis", "report")
    if basis not in YEAR_FIELDS:
        basis = "report"
    category = filters.get("category", "all")
    if category not in (*LEGAL_CATEGORIES, "all"):
        category = "all"
    compare_level = filters.get("compare_level", "department")
    if compare_level not in {"department", "municipality"}:
        compare_level = "department"
    if compare_level == "municipality" and not selected_department:
        compare_level = "department"

    applied = {"scope": scope, "department": selected_department,
               "municipality": selected_municipality, "basis": basis,
               "category": category, "compare_level": compare_level}
    data = _filtered_crimes(applied, basis)
    available_years = sorted(data[YEAR_FIELDS[basis]].dropna().astype(int).unique()) if not data.empty else []
    if not available_years:
        no_data = True
        field = YEAR_FIELDS[basis]
        available_years = sorted(crimes.loc[
            crimes["categoria"].isin(LEGAL_CATEGORIES) & crimes[field].notna(), field
        ].astype(int).unique())
    else:
        no_data = False
    if not available_years:
        raise ValueError("No complete year values are available in the processed dataset.")
    requested_year = filters.get("year")
    try:
        selected_year = int(requested_year)
    except (TypeError, ValueError):
        selected_year = min(max(LAST_COMPLETE_YEAR, available_years[0]), available_years[-1])
    if selected_year not in available_years:
        selected_year = min(available_years, key=lambda year: abs(year - selected_year))
    applied["year"] = selected_year

    series = _series_for(data, basis, applied)
    selected_rate_rows = series[series["year"] == selected_year]
    show_rate = (basis == "report" and not selected_rate_rows.empty
                 and pd.notna(selected_rate_rows.iloc[0]["rate_100k"]))
    comparison = _comparison_table(applied, basis, selected_year)
    metric = "rate_100k" if show_rate else "processes"
    forecast = _forecast(data, basis)
    trend_chart = _trend_chart(series, basis, show_rate)
    category_chart = _category_chart(
        _filtered_crimes({**applied, "category": "all"}, basis), basis)
    comparison_chart = _comparison_chart(comparison, metric)
    forecast_chart = _forecast_chart(series, forecast)

    legal_rows = int(crimes["categoria"].isin(LEGAL_CATEGORIES).sum())
    unclassified_rows = int((crimes["categoria"] == "NO_ESPECIFICADO").sum())
    known_total = float(crimes.loc[crimes["categoria"].isin(LEGAL_CATEGORIES), "total_procesos"].sum())
    population_years = []
    if not department_rates.empty:
        population_years = sorted(department_rates["report_year"].dropna().astype(int).unique())
    source_audit = inspect_original_sources()
    return {
        "filters": applied, "departments": departments, "municipalities": municipalities,
        "categories": [{"value": "all", "label": "All verifiable legal categories"}] +
                      [{"value": key, "label": value} for key, value in CATEGORY_LABELS.items()],
        "years": available_years, "selected_year": selected_year,
        "history": series.to_dict(orient="records"), "comparison": comparison,
        "trend_chart": trend_chart, "category_chart": category_chart,
        "comparison_chart": comparison_chart, "forecast": forecast,
        "forecast_chart": forecast_chart, "show_rate": show_rate, "no_data": no_data,
        "comparison_show_rate": any(row["rate_100k"] is not None for row in comparison),
        "rate_available_years": population_years,
        "data_summary": {"source_rows": len(crimes), "legal_rows": legal_rows,
                         "unclassified_rows": unclassified_rows,
                         "legal_processes": int(known_total),
                         "departments": int(crimes["departamento_hecho"].nunique()),
                         "municipalities": int(crimes[["departamento_hecho", "municipio_hecho"]]
                                                .drop_duplicates().shape[0]),
                         "first_year": int(crimes["ano_hechos"].min()),
                         "last_year": int(crimes["ano_hechos"].max()),
                         "partial_year": PARTIAL_YEAR,
                         "municipal_rate_rows": len(municipal_rates),
                         "department_rate_rows": len(department_rates),
                         "raw_source_rows": source_audit["crime_source_rows"],
                         "preprocessing_excluded_rows": max(
                             0, (source_audit["crime_source_rows"] or len(crimes)) - len(crimes)),
                         "raw_source_columns": source_audit["crime_source_columns"],
                         "raw_source_available": source_audit["crime_workbook_available"],
                         "population_source_available": source_audit["population_workbook_available"]},
    }
