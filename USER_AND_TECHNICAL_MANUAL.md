# User and technical manual

## User manual

### Access

1. Open the application and create an account with a name, email, and password of at least eight characters.
2. Sign in to reach the dashboard. Newly registered accounts have the `user` role. Do not include passwords, one-time codes, card numbers, or unnecessary sensitive information in incident descriptions.
3. Use **My History** to review your own saved model queries. Other users cannot open your history.

### Analyze a URL for phishing indicators

1. Open **Phishing Detection** from the dashboard.
2. Enter a URL with HTTP(S), or a hostname that can be normalized to HTTPS.
3. Review the estimated `Phishing` or `Legitimate` class and class scores.
4. The model only evaluates URL text and does not visit the destination. A `Legitimate` output does not establish that the site is safe. If you interacted with a suspected site, use the **Intelligent Cybersecurity Assistant**.

### Explore the cybercrime classifier

1. Open **Cybercrime Analysis** and complete the required dataset fields.
2. Review the predicted legal category estimate and model scores.
3. Treat this only as an academic demonstration: the model uses aggregated record attributes and has low legacy macro F1 (0.1176). It does not establish that a person committed an offense or classify an individual event reliably.

### Get guided security steps

1. Open **Intelligent Cybersecurity Assistant**.
2. Select Prevention, Active Incident, or Post-Incident and the closest problem type.
3. Mark the actions that actually occurred (for example: opened a link, submitted a password, ran a file, sent money, or lost account access). Describe only non-sensitive context.
4. Read the advisory urgency, why the rules assigned it, the ordered steps, each step's purpose and intended result, actions to avoid, evidence guidance, and official references.
5. Use **Start a new consultation** when the situation changes. The assistant does not save the description, contact a bank, block an account, or file a report. Its outcomes are not guarantees and do not replace an official or specialist response.

### Record and review an incident

1. Sign in and open **My Incidents**.
2. Choose a category, optional date, and description, then submit. This creates an internal record; it is not sent to external organizations.
3. Review the current status and workflow history on the incident page. A `user` sees only their own incident records. Users cannot edit or delete a submitted record in this version.
4. Analysts and admins can review all incidents and set `Open`, `Under Review`, `In Progress`, `Resolved`, or `Closed`, with an observation. Each update is recorded in the event history.

### Analyst and administrator tasks

- An analyst can open dataset/model evaluation, territorial analysis, the incident queue, reports, and CSV export. Analyst routes are protected on the server.
- An administrator can perform analyst tasks and manage user roles/account status through **User Administration**. The last active administrator cannot demote or suspend themselves through the web form.
- First-admin provisioning is an operator task; see below.

## Technical manual

### Components

| Component | Implementation |
|---|---|
| Web and templates | Flask routes in `app.py`; Jinja views in `templates/`; CSS in `static/css/`. |
| Crime model | Existing scikit-learn pipeline in `models/best_model.joblib`, loaded by `src/predict.py`. |
| URL model | Existing scikit-learn pipeline in `models/phishing_detector.joblib`, loaded by `src/phishing_predict.py`; no URL fetching. |
| Territorial analysis | `src/territorial_analysis.py` reads processed crime and rate CSVs and renders charts/tables. |
| Cybersecurity guidance | `src/cybersecurity_guidance.py`; deterministic scenario, status, and exposure-signal rules. |
| Persistence | SQLite tables `users`, `predictions`, `incidents`, and `incident_updates`; additive setup/migration in `ensure_user_database()`. |
| Authorization | `login_required`, `analyst_required`, and `admin_required` are server-side decorators. |
| Reports | Analyst/admin report context aggregates saved prediction rows; `/reports/export.csv` exports prediction metadata. |

### Local setup

```powershell
pip install -r requirements.txt
flask --app app.py run
```

The default local DB is `instance/cybercrime.sqlite3`; the local secret is created under `instance/`. These instance files are excluded from Git. To use another DB file, set `USER_DB_PATH` before starting the app.

### Production setup

Use the `Procfile` command `gunicorn app:app`. Set `APP_ENV=production`, `FLASK_SECRET_KEY` to a private value of at least 32 characters, and `COOKIE_SECURE=1` when HTTPS is enabled. Confirm that the deploy installs the pinned scikit-learn version and hydrates the large random forest artifact tracked through Git LFS.

Registration creates only `user` accounts. Register the intended admin, then from a trusted shell run:

```powershell
flask --app app.py promote-admin admin@example.com
```

The current DB engine is SQLite, not PostgreSQL. On Render, set `USER_DB_PATH` to a path mounted on a persistent disk if available. The service's default filesystem may be ephemeral; account/history/incident durability on the live service is **not verified**. If persistent SQLite storage is unavailable, implement and test a PostgreSQL adapter plus migration before using production for durable data. Never put database credentials or `FLASK_SECRET_KEY` in tracked files.

### Database and role notes

On startup, additive table/column creation adds roles and incident tables without replacing the existing user and prediction records. Roles are limited by server checks to `admin`, `analyst`, and `user`; the public registration form does not accept role input. Existing accounts migrate to `user` by default. Existing prediction history without model metadata displays version `Unknown`.

### Model version and metric notes

Crime model history captures the training timestamp in the stored input payload. Phishing history captures the scikit-learn and dataset metadata version. These identify the metadata used by the running app; they are not signed model provenance. The crime model's legacy split macro F1 is 0.1176 and used for model selection, so it is not an independent final estimate. Details of temporal/geographic evaluation and non-promotion are in `reports/crime_experiments/final_evaluation.md`.

### Tests and deployment checks

Run `.venv/Scripts/python.exe -m unittest discover -s tests -v` on Windows or `python -m unittest discover -s tests -v` in a standard environment. The documented final local suite result is 21 tests passing; local scikit-learn 1.9.1 emits compatibility warnings for the stored 1.8.0 artifacts. See [`DEPLOYMENT.md`](DEPLOYMENT.md) and [`ACTIVITY2_COMPLIANCE.md`](ACTIVITY2_COMPLIANCE.md) for production verification and pending items.
