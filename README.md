# Cybercrime Analytics Colombia

**Cybercrime Analysis and Prediction in Colombia Using Machine Learning**
Knowledge Management Project (PGC) - Universidad de Cundinamarca, Faculty of Engineering.

A Flask web information system that manages reports of suspicious URLs and integrates a
Machine Learning model that classifies them as **phishing** or **legitimate**. The whole
process is documented in the application with the six **CRISP-ML** phases.

- Published application: `<RENDER_URL>`
- Technical report (PDF): `<link>`

## What the system does

| Module | Who | What |
|---|---|---|
| PGC documentation | Public | Project overview and the six CRISP-ML phases with evidence |
| Authentication | Everyone | Registration, login, logout, password change, lockout after 5 failed attempts |
| Case management | Reporter, analyst | Report suspicious URLs; create, read, update and delete cases |
| Classification | Analyst | Server-side inference, risk level, recommended action, explanation |
| Review | Analyst | Take a case, record the verdict (actual outcome) and the action, close or reopen |
| Inference history | Analyst | Every prediction with date, user, result and model version |
| Reports | Analyst | Indicators, charts, Colombian open-data context, CSV exports |
| Monitoring | Administrator | Requests, errors, response times, drift (PSI), live performance, alerts |
| Incidents and feedback | Everyone / administrator | Report wrong results or errors; administrator answers |
| Administration | Administrator | Roles and account activation |

Roles: **reporter** (default for new accounts), **analyst**, **administrator**. Administrators
are created only from the command line; nobody can assign themselves a role.

## Architecture

```
Browser ──HTTPS──> Flask app (gunicorn on Render)
                     ├── blueprints: docs, auth, account, admin, cases, predictions,
                     │               reports, monitoring, feedback, model
                     ├── ml/features.py   URL -> features (same rules as the dataset)
                     ├── ml/service.py    loads models/*.joblib + metadata, predicts
                     ├── ml/inference.py  stores predictions, sets priority and action
                     ├── ml/drift.py      PSI, live performance, alert rules
                     └── SQLAlchemy ──> PostgreSQL (Render) / SQLite (local)
```

## Repository structure

```
analysis/        Data Engineering scripts (01-09) and EDA figures
data/            raw (see data/README.md) and processed datasets
models/          model artifacts and the model contract (models/README.md)
cyberapp/        Flask application (blueprints, models, ml, monitoring)
templates/       Jinja templates (phases/ = CRISP-ML documentation)
static/          CSS and JavaScript
scripts/         build_reference_stats.py, check_feature_parity.py
tests/           pytest suite
docs/            technical manual, user manual and training guide
render.yaml      Render deployment (web service + PostgreSQL)
```

## Run locally

Requirements: Python 3.13 (3.12+ works) and Git.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # Linux/macOS: cp .env.example .env  -> set SECRET_KEY
flask --app app init-db
flask --app app create-admin
flask --app app run --debug
```

Open http://127.0.0.1:5000. Optional demo data (labeled SIMULATED):
`flask --app app seed-demo` (remove it with `flask --app app clear-demo`).

### Tests

```bash
python -m pytest
```

## Reproduce the data and model pipeline

1. Download the raw files listed in `data/README.md` into `data/raw/`.
2. Data Engineering: run `analysis/01_read_data.py` to `analysis/09_rate_charts.py` in order.
3. Model Engineering: train and evaluate the models and save `models/phishing_model.joblib`
   and `models/model_metadata.json` following `models/README.md`.
4. Reference statistics for explanations and drift: `python scripts/build_reference_stats.py`.
5. Optional check that the app computes the same features as the dataset:
   `python scripts/check_feature_parity.py`.

## Deploy to Render

1. Push the repository to GitHub.
2. Render dashboard -> **New** -> **Blueprint** -> select the repository. `render.yaml` creates
   the web service and the PostgreSQL database and generates `SECRET_KEY`.
3. When the first deploy finishes, open the service **Shell** and run
   `flask --app app create-admin` (and optionally `flask --app app seed-demo`).
4. Check `https://<your-service>.onrender.com/healthz`.

Notes: the free web service sleeps after inactivity (first request takes ~1 minute) and the
free PostgreSQL database has an expiration date; upgrade or recreate it before it expires.

### Environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Session signing key (required in production) |
| `DATABASE_URL` | PostgreSQL URL; empty = `instance/cybercrime.db` (SQLite) |
| `SESSION_COOKIE_SECURE` | `1` when served over HTTPS |
| `BEHIND_PROXY` | `1` behind Render's proxy (correct HTTPS URLs and client IPs) |
| `MODEL_DIR` | Folder with the model artifacts (default `models/`) |

## Command line

| Command | Purpose |
|---|---|
| `flask --app app init-db` | Create the database tables |
| `flask --app app create-admin` | Create an administrator |
| `flask --app app seed-demo` / `clear-demo` | Create / delete simulated demo data |
| `flask --app app monitoring-report --days 7` | Print the operational review |

## Documentation

- [Technical manual](docs/TECHNICAL_MANUAL.md)
- [User manual](docs/USER_MANUAL.md)
- [Training guide](docs/TRAINING_GUIDE.md)
- [Model contract](models/README.md)
- [Data sources](data/README.md)

## References

- Schmid, Wurst & Wirth (2020). *Towards CRISP-ML(Q): A Machine Learning Process Model with Quality Assurance Methodology.*
- ML-Ops.org. *CRISP-ML(Q): The ML Lifecycle Process.*
- KDnuggets (2025). *The Machine Learning Lifecycle.*
- Prasad, A. & Chandra, S. (2024). *PhiUSIIL Phishing URL Dataset.* UCI Machine Learning Repository.
- Fiscalía General de la Nación. *Delitos Informáticos.* datos.gov.co.
- DANE. *Proyecciones de población municipal 2018-2042.*
