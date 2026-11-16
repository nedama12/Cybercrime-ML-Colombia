# Project data

## Raw data

- `Delitos_Informaticos_V1_20261010.xlsx`: source workbook used for the Colombian cybercrime
  analysis. The date in the filename is 2026-10-10. Preserve the original file unchanged.
- `PhiUSIIL_Phishing_URL_Dataset.csv`: separate URL-phishing dataset. If it is not present in
  the repository, obtain it from the UCI Machine Learning Repository before running the
  phishing preparation/training scripts.
- `PPED-AreaMun-2018-2042_VP.xlsx`: DANE municipal population projection workbook. If it is
  not present in the repository, obtain the relevant municipal population series from DANE
  before running the population-rate scripts.

## Processed data

The analysis scripts generate processed tables under `data/processed/`. Depending on the
available source files and scripts, these can include:

- `crimes_processed.csv` or `delitos_procesado.csv`: cleaned cybercrime records. These names
  are not interchangeable unless the consuming scripts and serialized model schemas agree.
- `summary_year_category.csv` and `summary_department_category.csv`: aggregated summaries.
- `rates_department_year.csv` and `rates_municipality_year.csv`: rates per 100,000 inhabitants
  for matching territory/year keys.
- Phishing features and derived data, if the separate URL model pipeline is used.

Do not rename columns or replace processed datasets without checking the feature names stored
in the corresponding serialized model pipeline.

## Incident report classifier data

- `data/reports/seed_reports.csv`: team-authored seed examples used by the incident narrative
  classifier. These are not real victim reports.
- `data/reports/realistic_holdout.csv`: separately authored examples used for evaluation.
  Keep the holdout separate from training.
- Analyst-confirmed reports may be eligible for later training only through the documented
  training workflow and appropriate privacy controls. Do not copy real personal information
  into public datasets.

## Reproducing the data analysis

Run from the repository root after installing `requirements-analysis.txt` and providing the
required source files:

```powershell
python analysis/03_cleaning.py
python analysis/06_eda_crimes.py
python analysis/08_population_merge.py
python analysis/09_rate_charts.py
```

The exact available scripts and expected filenames should be checked in `analysis/` before
running. Some scripts require source workbooks that are not included in the repository.
