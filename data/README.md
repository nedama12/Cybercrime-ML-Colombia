# Project data

## Raw data

- `Delitos_Informaticos_V1_20261010.xlsx` is the source workbook for Colombian cybercrime records. Its name contains the date 2026-10-10.
- `PhiUSIIL_Phishing_URL_Dataset.csv` is not stored in this repository. Download it from the [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+website+dataset) and save it under `data/raw/` before running the phishing preparation scripts.
- `PPED-AreaMun-2018-2042_VP.xlsx` is not stored in this repository. Download the municipal population projection workbook from [DANE](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion) and save it under `data/raw/` before running the population scripts.

## Processed data

The crime classification web application reads `data/processed/delitos_procesado.csv`. The analysis scripts also create summary tables, population rates, and phishing features in this directory. Source column names are kept as supplied by the Colombian crime dataset because the trained model depends on them.

## Reproducing the analysis

Run these commands from the repository root after installing `requirements-analysis.txt` and providing the required raw datasets:

```text
python analysis/03_cleaning.py
python analysis/05_prepare_phishing.py
python analysis/06_eda_crimes.py
python analysis/08_population_merge.py
python analysis/09_rate_charts.py
```
