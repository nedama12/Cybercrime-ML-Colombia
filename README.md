# Cybercrime Colombia

Academic Flask information system for Colombian cybercrime reporting and analysis. The
incident-reporting workflow is designed around the CRISP-ML phases and separates the
classification of a citizen's narrative from the analysis of aggregated official records.

## Main workflow

A citizen submits a description of a cybercrime incident and follows the status of the report.
The incident text classifier (referred to in the project as **Astrith**, where configured)
predicts a category to support triage. Analysts review reports and can confirm or correct the
classification. Administrators manage privileged access and system operations.

The classifier is a decision-support component, not a legal authority and not a replacement
for filing a formal complaint. Model results must be interpreted using the evaluation evidence
and limitations documented in `reports/`.

## Main modules

| Module | Purpose |
|---|---|
| Citizen reports | Submit and follow incident reports |
| Analyst review | Review reports, add observations and confirm classifications |
| Administration | Manage users and privileged roles |
| Territorial analysis | Explore aggregated Colombian cybercrime records by territory and time |
| Cybersecurity guidance | Provide first-response guidance; this is rule-based if implemented by `src/cybersecurity_guidance.py` |
| URL phishing analysis | Separate URL-text model, only if its model artifact and route are present |
| CRISP-ML documentation | Business/data understanding, engineering, evaluation, deployment and monitoring |

Check the live route list with `python -m flask --app app routes`; routes can change between
branches and this table is a project overview, not a guarantee that every route is enabled.

## Machine-learning components: keep them separate

1. **Incident narrative classifier (Astrith):** classifies the citizen's written description.
   Its implementation and training flow are associated with `src/report_model.py` and
   `src/train_report_model.py` in the incident-reporting design. It must not be replaced by
   the territorial benchmark.
2. **Territorial/location benchmark:** uses aggregated features such as department,
   municipality and year to study whether legal categories can be inferred from those fields.
   It is not an individual-incident classifier. The supplied comparison chart shows low
   macro-F1 values for this benchmark; those results are not Astrith's performance.
3. **Phishing URL model:** a separate URL-text classifier, if enabled. It analyzes the URL
   string and does not visit the destination or inspect page contents.

Do not compare the metrics of these different tasks as if they measured the same model.

## CRISP-ML project map

The feature branch documents these phases and associated routes:

| Phase | Route shown in project documentation | Subject |
|---|---|---|
| Business and data understanding | `/business` | Problem, stakeholders, objectives, data and risks |
| Data engineering | `/dataset` | Cleaning, transformations, features and partitions |
| Model engineering | `/models` | Candidate models and experiment log |
| Model evaluation | `/evaluation` | Metrics, comparison and limitations |
| Deployment | `/deployment` | Artifacts and deployment procedures |
| Monitoring and maintenance | `/monitoring` | Monitoring indicators and maintenance plan |

Confirm the actual route names with Flask before recording a demo or publishing.

## Repository structure

```text
app.py                         Flask application
src/report_model.py            Incident narrative classification service
src/train_report_model.py      Incident classifier training/evaluation
src/territorial_analysis.py    Territorial and temporal analysis
src/train.py                   Safe entry point for the separate crime benchmark experiment
src/predict.py                 Prediction helper for the location benchmark
src/verify_models.py           Model artifact smoke checks
src/cybersecurity_guidance.py  First-response guidance rules, if present
analysis/                       Data preparation and exploratory scripts
data/                           Raw, processed and report datasets
models/                         Serialized model artifacts and metadata
reports/                        Evaluation reports, metrics and figures
templates/                      Jinja templates
static/                         CSS, JavaScript and static assets
tests/                          Automated tests
```

## Local setup

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m py_compile app.py
python -m flask --app app routes
python app.py
```

Open `http://127.0.0.1:5000`. Use fictional test data when demonstrating report submission.

For data engineering or model retraining, install `requirements-analysis.txt` if needed and
consult `data/README.md` for the required source files. Do not retrain production artifacts
as part of a routine application start.

## Evaluation and limitations

The location benchmark's confusion matrices and comparison chart are supporting evidence for
that separate task. The benchmark has weak macro-F1 performance in the supplied results and
must be described as exploratory. The incident narrative classifier has its own test and
realistic-holdout results; consult the corresponding reports and verify the exact model
version before quoting a metric.

The incident classifier's performance on a small realistic holdout is not proof of equivalent
performance on real-world reports. Seed examples are team-authored and are not real victim
records. Analyst-confirmed reports should be included in future evaluation only with a
documented data-governance process and a clean separation between training and test data.

Territorial process counts are not necessarily counts of individual incidents or estimates
of total crime prevalence. Forecasts are exploratory, not official projections. URL-text
phishing scores do not prove that a destination website is safe.

## Data and privacy

Do not commit SQLite databases, passwords, secret keys, real incident narratives, credentials,
or personal data. Citizen accounts must only access their own records. Analyst/admin access
must be enforced server-side. The application does not replace a formal criminal complaint.

## Tests and verification

Run the tests that are present in the repository:

```powershell
python -m unittest discover -s tests -v
```

Run model smoke checks only after confirming the required model artifacts and datasets are
present:

```powershell
python -m src.verify_models
```

See `DEPLOYMENT.md` for deployment configuration and post-deployment checks.
