# Cybercrime Colombia

Machine learning project developed with the six phases of CRISP-ML and documented in a Flask
application. A citizen reports a cybercrime in about 90 seconds; a Logistic Regression text
classifier identifies its legal category (Law 1273 of 2009) and the platform shows practical
first steps, the official channels to file a formal complaint and the status of the report.
Analysts confirm each category; confirmed reports become new training data.

- **Published application:** `https://<render-service>.onrender.com`
- **Selected model:** Logistic Regression (C = 8), cross-validated macro F1 0.956 ± 0.010,
  accuracy 96.7 % on unseen phrases and 97.8 % on the realistic holdout.

## Application map (CRISP-ML)

| Phase | Route | Content |
|---|---|---|
| 1 Business and data understanding | `/business` | Problem, stakeholders, objectives, data, risks, success criteria |
| 2 Data engineering | `/dataset` | Cleaning before/after, transformations, features, partitions |
| 3 Model engineering | `/models` | Candidates, configuration, grouped CV tuning, experiment log |
| 4 Model evaluation | `/evaluation` | Metrics, comparison, overfitting, expert review, final test |
| 5 Deployment | `/deployment` | Live demo, artifacts, inputs/outputs, run instructions, procedures |
| 6 Monitoring and maintenance | `/monitoring` | Indicators, drift, schedule, simulated monitoring test |
| Model demo with history | `/report` | Account, 3-step report, result, next steps, official channels |
| Analyst workspace | `/review` | Confirm categories, close reports, live indicators |

## Repository structure

```
app.py                      Flask application (routes, accounts, reports, review)
src/build_seed_corpus.py    Seed corpus of victim-style reports
src/train_report_model.py   Grouped CV tuning, selection and final evaluation (selected model)
src/report_model.py         Inference service used by the app
src/train.py                Location benchmark on official data
src/data_quality.py         Before/after evidence of the cleaning
src/monitoring.py           Monitoring test with simulated operational data
analysis/                   Data engineering scripts (cleaning, exploration, population rates)
data/                       Raw, processed and report datasets (see data/README.md)
models/                     Saved pipelines, model info and drift reference
reports/                    Metrics, experiments, figures, monitoring log, technical report
templates/, static/         Pages and styles
tests/                      21 automated tests
```

## Reproduce

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-analysis.txt      # only to rerun the data engineering scripts

python analysis/03_cleaning.py                # raw Excel -> data/processed/crimes_processed.csv
python -m src.data_quality                    # before/after evidence
python -m src.build_seed_corpus               # seed corpus
python -m src.train_report_model              # tuning, selection, final evaluation (~3 min)
python -m src.train                           # location benchmark
python -m src.monitoring                      # monitoring test (simulated data)
python -m src.verify_models
python -m unittest discover -s tests
python app.py                                 # http://127.0.0.1:5000
```

All model artifacts are versioned in `models/`, so the app runs without retraining. To try the
analyst view locally: `$env:ANALYST_EMAILS = "analyst@example.test"; python app.py` and register
with that email, or `flask --app app make-analyst someone@example.test`.

See `reports/MODEL_ENGINEERING_REPORT.md` for methods and results, `data/README.md` for data
sources and `DEPLOYMENT.md` for deployment and security settings.

## Data and privacy

Accounts and reports are stored in `instance/cybercrime.sqlite3` (excluded from Git). Passwords
are stored as scrypt hashes, every form uses a CSRF token and each citizen only sees their own
reports. The platform does not replace a formal criminal complaint.
