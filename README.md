# Cybercrime ML Colombia

An academic Flask application that explores Colombian cybercrime records and demonstrates a supervised multiclass classifier.

## Run the application

```powershell
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`, create an account, and submit an example through the prediction page. The application displays the predicted category and each class probability, then stores the input and output in the signed-in user's history.

## Machine learning task

This project performs supervised machine learning: three scikit-learn classifiers are trained on labeled records, compared, and saved as serialized pipelines. The target is `categoria`. The stored pipeline predicts one of nine categories from incident indicator, department, municipality, regional office, and year fields. Numeric imputation, scaling, and categorical encoding are part of the saved pipeline.

The current selected model is Logistic Regression. Its saved test-set macro F1 is approximately 0.118 and accuracy is approximately 0.140. These scores are low. The prediction page is an academic demonstration and its output should not be used for operational or legal decisions. Class probabilities are model scores, not calibrated confidence estimates.

The existing model selection score was calculated from the same 80/20 test results displayed in the report. This means the test set was used both to compare and select the model; the displayed scores are not an independent final estimate and may be optimistic. A final project evaluation should use a separate validation split for selection and keep the test set untouched until the model is fixed.

## Project files

- `data/processed/delitos_procesado.csv`: processed source dataset consumed by the current trained model. Source column names are retained because they are part of the serialized model's input schema.
- `models/`: serialized scikit-learn pipelines and model metadata.
- `reports/`: comparison metrics, class reports, confusion matrices, and the project report.
- `analysis/`: data preparation and exploratory analysis scripts.
- `src/train.py`: leakage-aware crime model experiment entry point (`python -m src.train`); writes a candidate and reports without replacing the active model.
- `src/predict.py`: prediction interface used by the web application.
- `src/verify_models.py`: artifact loading and sample inference check (`python -m src.verify_models`).

## Cybercrime Territorial and Temporal Analysis

Open **Territorial Analysis** from the navigation or dashboard, or visit `/territorial-analysis`. The module analyzes aggregated process counts by department, municipality, legal category, and either report year or event year. It excludes the 329 rows without a verifiable article from legal-category charts and explains why process counts are not counts of individual incidents or estimates of total crime prevalence.

Population rates are calculated per 100,000 residents only for matching report years and exact normalized territory keys available in `data/processed/rates_department_year.csv` and `data/processed/rates_municipality_year.csv`. These tables cover 2018–2025. The original projection workbook is not present in `data/raw`, so the municipality-to-population code mapping cannot be independently audited; treat municipal rates cautiously. No new fuzzy geographic matching is performed by the web module.

Annual exploratory forecasts compare a three-year moving average with a linear trend using rolling one-year validation over 2023–2025 and mean absolute error (MAE). The selected baseline is refit through 2025 to estimate 2027–2029. The source marks 2026 partial, so that year is excluded from forecast fitting and validation. Forecasts are not official projections and do not include prediction intervals, changes in reporting, population, or policy.

## Cybercrime classifier evaluation

The reproducible comparison entry point is `python -m src.experiment_crime` (also available through `python -m src.train`). It evaluates leakage-aware pipelines with grouped validation, an unseen-department test, and a separate temporal validation/test. The full model table, per-category reports, confusion matrices, and non-promotion decision are documented in [`reports/crime_experiments/final_evaluation.md`](reports/crime_experiments/final_evaluation.md). The active Logistic Regression model was kept because no candidate showed reliable gains across both geography and time. Do not use `DELITO`, article codes, or their derivatives as predictors: they reveal the target. The current input fields do not include enough incident facts to support an individual-incident detector.

## Intelligent Cybersecurity Assistant

Open `/assistant` from the navigation without signing in. Choose a problem and incident status, then describe the situation in English. The assistant covers phishing, account theft, identity impersonation, transfer fraud, malware, unauthorized access, personal information exposure, systems attacks, data loss, and digital-platform fraud. It requests clarification when it cannot safely categorize a short or vague description.

The first-response plan is generated by explicit keyword, status, and exposure-signal rules in `src/cybersecurity_guidance.py`; it is not an ML classifier or a generative AI service. The user can mark whether they clicked a link, exposed a password or code, downloaded/opened a file, transferred money, lost account access, or shared personal information. These signals change urgency and the immediate steps, and the result explains what the situation may mean and why it assigned the priority. Each action includes a reason and an intended outcome; intended outcomes are not guarantees. Plans sequence immediate response, containment, recovery, information protection, prevention, escalation, and evidence preservation. Transfer fraud triggers immediate official-bank contact guidance; loss of account access raises urgency; opening a file adds device containment steps. Descriptions are limited to 2,000 characters, processed for the response, and not written to history or a database. The UI warns users not to enter passwords, OTP codes, or full banking details. Guidance is general and does not replace a bank, technical specialist, or legal professional.

The URL prediction screen now links model output to the assistant and explicitly cautions that a legitimate URL-text label does not prove site safety. The cybercrime result screen explains that the low-performing classifier works on aggregated legal-process records, not individual incidents. The territorial analysis remains a separate descriptive module: process counts are not prevalence or causal claims.

## Project purpose and limits

The platform studies available Colombian cybercrime process records to explore temporal and territorial patterns and evaluate whether the available aggregate fields support legal-category classification. It addresses the gap between analysis and accessible first-response guidance. The data are processed records from the project workbook and derived rate tables; phishing training uses the separate PhiUSIIL UCI dataset. Flask, Python, pandas, scikit-learn, SQLite, joblib, and Matplotlib support the web, analysis, models, persistence, and charts. Users can explore records and trends, submit academic classification examples, check URL text, and request non-persistent rule-based guidance.

The crime classifier's legacy macro F1 is about 0.14 (the detailed temporal/geographic validation reports lower scores for several candidates). Its predictors lack incident narratives and technical evidence; the result is unsuitable for decisions about real cases. A model classification is not a legal conclusion. URL model scores are estimates from text features and cannot verify the destination page. Territorial figures count recorded processes and reporting can vary over time; they do not establish true prevalence or causes. Forecasts are exploratory baselines, not official projections. These limits are surfaced in the relevant module pages and reports.

## Phishing Detection

The second model is independent from the Colombian cybercrime classifier. It uses the original [PhiUSIIL dataset from UCI](https://archive.ics.uci.edu/dataset/967/phiusil+phishing+url+dataset) only for training and validation. UCI defines `0 = phishing` and `1 = legitimate`; the saved predictor maps its own output to `phishing` / `legitimate`.

Copy the original CSV to `data/raw/PhiUSIIL_Phishing_URL_Dataset.csv`, or pass its current location directly:

```powershell
python -m src.train_phishing --data "C:\path\to\PhiUSIIL_Phishing_URL_Dataset.csv"
```

Training removes invalid rows and repeated URLs, groups splits by normalized URL host (merging the conventional `www` alias), compares URL-character Logistic Regression, Complement Naive Bayes, and URL-syntax Logistic Regression / Random Forest on validation, then evaluates the selected model once on held-out test hosts. The selected predictor uses URL text only. It never visits the submitted URL or reads page content. Subdomains are treated as separate hosts, so the held-out results do not prove generalization to every new registrable domain.

Artifacts are stored separately in `models/phishing_detector.joblib` and `models/phishing_detector_info.json`; evaluation outputs go to `reports/phishing/`. Use `python -m src.phishing_predict "https://example.com/path"` for command-line inference. In Flask, sign in and choose **Phishing Detection** from the prediction page.

The prediction history stores the model type and metadata version in each record's existing `incident_json` payload. The original SQLite tables remain compatible through additive migrations.

## Roles, incident workflow, and live reports

Registration creates a `user` role; public input cannot set privileged roles. `analyst` and `admin` access is enforced in Flask routes. Analysts and admins can access analysis pages and reports; only admins can manage roles and account status. Create an initial administrator by registering that account and running `flask --app app.py promote-admin email@example.com` from a trusted shell. See [`DEPLOYMENT.md`](DEPLOYMENT.md).

Signed-in users can record internal incidents at **My Incidents**. They can view only their own records; analysts and admins can review the queue and add status/observation events. The internal incident log does not contact external entities. Analysts/admins can view calculated activity metrics and export prediction records as CSV at **Reports**. User emails in the activity report are visible only to authorized staff.

See the [User and Technical Manual](USER_AND_TECHNICAL_MANUAL.md) for workflows and operations, and [`ACTIVITY2_COMPLIANCE.md`](ACTIVITY2_COMPLIANCE.md) for the requirement matrix, metric caveats, verification status, and remaining work.

## Checks

Run the territorial filters/forecast, account, ML input, history isolation, additive migration, assistant decision rules, role permissions, incident workflow, and report export checks with:

```powershell
python -m unittest discover -s tests -v
```

Model files were created with scikit-learn 1.8.0. Use the pinned dependency version in `requirements.txt` when loading them.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for environment variables, secure cookie settings, the startup command, first-admin provisioning, and storage requirements. Local accounts, prediction history, and incident workflow records are stored in `instance/cybercrime.sqlite3`, which is excluded from version control. Render production storage still needs a mounted persistent disk or a separately implemented PostgreSQL backend.
