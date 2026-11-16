# Activity 2 — implementation and verification record

This document records the current local implementation. “Completed” means the code path and corresponding local test/check exist; it does not imply that Render has deployed the current working tree.

## System overview

Cybercrime-ML-Colombia is an existing Flask research platform for processed Colombian cybercrime process records. It includes separate URL-text phishing and aggregated-record crime classifiers, descriptive territorial and temporal analysis, an account-owned prediction history, a rule-based cybersecurity guide, role-controlled analysis pages, incident workflow records, and application activity reports.

### Architecture and technology

- Flask routes and Jinja templates provide the web application; `static/css` contains its styles.
- pandas reads prepared CSV datasets; scikit-learn pipelines are persisted with joblib; Matplotlib creates analysis charts.
- SQLite stores users, prediction history, incident records, and incident workflow updates. `ensure_user_database()` applies additive schema updates on startup and preserves existing account/prediction tables.
- `Procfile` declares `gunicorn app:app`; `requirements.txt` pins scikit-learn 1.8.0, the model artifact version recorded in metadata.
- The cybersecurity guide uses deterministic rules. There is no generative-AI service or external incident-response integration.

### CRISP-ML(Q) relationship

The project follows parts of a CRISP-ML(Q)-style cycle: problem/data understanding in the analysis scripts and documentation; data preparation in the processed datasets; model engineering in `src/`; evaluation in `reports/` with temporal/geographic checks; and deployment of the existing Flask application. Continuous production monitoring, formal model governance, and automatic quality gates are not implemented. This is a partial methodological alignment, not a claim of full CRISP-ML(Q) compliance.

## Roles, accounts, and data access

- Registration always creates a `user`; there is no role field in the public registration form.
- Passwords use Werkzeug secure hashes. Login/logout, CSRF-protected write forms, server-side validation, eight-hour sessions, secure cookie options, and an in-process five-failure login throttle are implemented.
- `admin`, `analyst`, and `user` roles are checked in Flask route decorators. Analysis/report routes require analyst or admin. User administration requires admin. Users can see only their own prediction history and incident records; analysts/admins can review the incident queue and reports.
- Admins can change roles and suspend/reactivate accounts. The last active admin cannot be demoted or suspended through the web form. Account deletion is deliberately not exposed, preserving references and audit history.
- To create the first admin, create a normal account, then run `flask --app app.py promote-admin email@example.com` from a trusted shell. The command cannot grant access to an account that does not already exist.

## Machine-learning modules

### Phishing Detection

`models/phishing_detector.joblib` and its metadata are present and used by `src/phishing_predict.py`. Input is validated and normalized as HTTP(S) URL text; the submitted destination is never resolved, fetched, or executed. The prediction and URL are saved in the signed-in user's history with a model metadata version. Displayed class probabilities are estimates, not calibrated guarantees. The evaluation metadata reports a held-out host-split test macro F1 of approximately 0.997, but the split groups hosts and subdomains separately; it does not prove generalization to all newly registered domains. The original training CSV is intentionally not included.

### Cybercrime Analysis

The active Logistic Regression artifact remains unchanged. Its legacy random-split macro F1 is 0.1176 and accuracy 0.1398; model selection reused the displayed test set, so this is not an independent final estimate. Separate grouped, temporal, and geographic experiments are documented in `reports/crime_experiments/final_evaluation.md`; candidate models were not promoted. The inputs are mostly territory, dates, and a criminality indicator, not incident narratives or technical evidence. The output estimates a category for an aggregate process record, not an individual incident and not an official legal classification. Probabilities are classifier estimates, not demonstrated calibrated confidence. Saved predictions include the model training-date metadata version.

### Territorial and Temporal Analysis

`/territorial-analysis` uses `src/territorial_analysis.py` and processed crime/rate tables. It supports department, municipality, category, year basis/year, and territory comparison filters with charts and tables. Counts describe recorded processes, not all crime. Population rates use only available matched denominators; the underlying population projection workbook/crosswalk is absent from the repository and requires independent audit. Forecasts are exploratory baselines with rolling validation, exclude the marked partial 2026 year from fitting, and are not official forecasts or causal explanations.

## Intelligent Cybersecurity Assistant

`/assistant` is a guided, non-persistent rule engine in `src/cybersecurity_guidance.py`, not a generic open-ended chatbot. It accepts Prevention, Active Incident, or Post-Incident status, a structured situation category, exposure signals (clicked link, credential/code exposure, downloaded/opened file, transfer, account loss, or shared personal data), and an optional description. Explicit rules determine the scenario, state, and advisory urgency; the result explains why, what the situation may mean, ordered actions, the reason for each action, intended result, actions to avoid, evidence, and official Colombian references. It asks for clarification when a free-text “Other” report is too vague. Descriptions are capped, used for the response only, and not stored. It does not file a report, block an account, or contact a third party. Guidance is not legal, banking, or specialist advice; intended outcomes are not guarantees.

## Incident workflow and reports

Signed-in users can create and read their own incident records. Records have category, description, optional date, status, timestamps, and a status/observation event history. Analysts/admins can see the queue and update status/observations. Supported states: Open, Under Review, In Progress, Resolved, Closed. This is an internal case log, not a connection to an authority or bank. Record deletion and user editing after submission are not implemented.

Analyst/admin reports calculate totals, phishing checks, crime-model category estimates, monthly activity, territories present in saved crime-model inputs, and (admin only) activity by user from actual saved prediction rows. CSV export contains prediction metadata and input territory fields, not incident narrative text. These are counts of queries, not measurements of cybercrime prevalence.

## Local installation and operations

```powershell
pip install -r requirements.txt
flask --app app.py run
```

Set `FLASK_SECRET_KEY` (at least 32 characters) and `APP_ENV=production` in production. Set `COOKIE_SECURE=1` over HTTPS. Use `USER_DB_PATH` to select the database file. Register an account, promote the first admin from a trusted shell, then assign analyst roles through **User Administration**. Set a persistent database path on a mounted Render disk if using SQLite; Render's ephemeral filesystem does not preserve SQLite across instance replacement. A PostgreSQL adapter/migration is not included. If a persistent disk is unavailable, provision a database backend and migrate before relying on production account/history persistence.

Render deployment command is `gunicorn app:app` (also declared in `Procfile`); build with `pip install -r requirements.txt`. Model files are committed, with the large random forest tracked through Git LFS. Confirm the Render deploy fetches LFS content and that all model artifacts load. The public Render state could not be verified from this environment because the HTTP request timed out; do not treat local route tests as proof of production deployment.

## Verification and known gaps

Run all automated checks:

```powershell
python -m unittest discover -s tests -v
```

Final local run: `.venv/Scripts/python.exe -m unittest discover -s tests -v` completed **21 tests in 72.736 seconds, OK**. Coverage includes registration, password hashing, login/logout, lockout, prediction/history ownership, additive migration, phishing URL validation and inference, assistant rules/routes, RBAC/bootstrap, incident ownership/validation/review history, report export permissions, and territorial filtering/rendering. The run emitted `InconsistentVersionWarning` because local scikit-learn 1.9.1 loaded artifacts recorded as 1.8.0; production should use the pinned `requirements.txt` environment. Local success is not evidence of Render deployment.

| Requirement | Implementation Status | Evidence | Pending Work |
|---|---|---|---|
| Registration, login/logout, password hashing, CSRF, session and login throttling | Completed | `app.py`; `tests/test_user_prediction_flow.py` | Rate limit is in-memory per worker; consider shared limiter for multiple workers. |
| Server-side roles and first-admin bootstrap | Completed | `roles_required`, `promote-admin`, `tests/test_roles_incidents_reports.py` | Create/promote first production admin in Render shell. |
| Admin user/role management and account suspension | Partial | `/admin/users`; `templates/admin_users.html`; role tests | Account deletion and full user CRUD are not implemented. |
| Private per-user prediction history and model version metadata | Completed | `save_prediction`, `/history`; user flow tests | Existing old history rows show version “Unknown”. |
| Phishing URL model integration and URL non-fetch behavior | Completed | `src/phishing_predict.py`; model artifact; `test_territorial_analysis.py` flow | Re-run model tests with pinned scikit-learn 1.8.0; current local environment emits a version warning. |
| Cybercrime classifier evaluation and limits | Completed | `models/best_model_info.json`; `reports/crime_experiments/final_evaluation.md`; UI caveat | Collect incident-level descriptive features before proposing a different task/model. |
| Territorial/temporal analysis and local route | Completed | `src/territorial_analysis.py`; `tests/test_territorial_analysis.py` | Render production route remains Not Verified. |
| Guided cybersecurity response workflows | Completed | `src/cybersecurity_guidance.py`; `tests/test_cybersecurity_assistant.py` | Expert review of advice and periodic verification of official URLs recommended. |
| Incident create/read/status workflow and audit trail | Partial | `/incidents`; `/incidents/<id>`; `tests/test_roles_incidents_reports.py` | Full CRUD is incomplete: no delete or reporter edit after submit. |
| Activity reports and CSV export | Completed | `/reports`; `/reports/export.csv`; RBAC tests | Reports cover saved model queries, not incidents or external reporting. |
| Entire interface English and CRISP-ML(Q) alignment | Partial | English Jinja screens; this document | Full UI copy audit and continuous quality/governance phases remain. |
| Render route, model loading, LFS and persisted database | Not Verified | Deployment instructions and `Procfile` only | Deploy changes, verify LFS artifacts, test routes, and configure durable storage. |
| PostgreSQL persistence backend | Pending | SQLite is the implemented backend | Add a supported DB adapter/schema migration if Render persistent disk is unavailable. |
