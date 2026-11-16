# Deployment and security configuration

This guide describes the configuration expected by the Flask application. Confirm each
setting against the current `app.py`, `render.yaml` and Render service before deploying:
the existence of a setting in this document does not prove it is configured in the live service.

## Environment variables

- `APP_ENV=production`: enables production configuration and requires an externally supplied secret.
- `FLASK_SECRET_KEY`: private, stable secret of at least 32 characters. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it in Render's
  environment settings. Never commit it.
- `COOKIE_SECURE=1`: enables secure session cookies when serving over HTTPS.
- `USER_DB_PATH`: optional path to the SQLite database. On a Render persistent disk, a typical
  value is `/var/data/cybercrime.sqlite3`.
- `ANALYST_EMAILS`: comma-separated addresses, only if the current application supports
  granting analyst role from this setting.
- `ADMIN_EMAILS`: comma-separated addresses, only if the current application supports
  administrator bootstrap from this setting.
- `BEHIND_PROXY=1`: use only if the application is configured to trust the Render proxy.
- `PORT`: optional HTTP port; Render normally supplies it.

In development, the application may create a local secret under `instance/`. Do not reuse a
development secret in production. Keep passwords, API keys, database files and private user
data out of Git.

## Build and start

The expected Render build command is:

```bash
pip install -r requirements.txt
```

The expected start command is:

```bash
gunicorn app:app
```

Use these commands only after confirming that `requirements.txt`, `app.py` and `Procfile`
match the deployed branch. Deploy the model artifacts required by the application; do not
assume Git LFS files have been downloaded correctly. Check the Render build log for LFS
pointer files or missing model artifacts.

## Persistent database storage

The application uses SQLite according to the project configuration. Files on a web service's
ephemeral filesystem can be lost when the service is replaced or redeployed. If the selected
Render plan supports a persistent disk, mount it (for example at `/var/data`) and set
`USER_DB_PATH=/var/data/cybercrime.sqlite3` only if the application reads that variable.
Back up the database before deployments and test that records survive a service restart.

If a persistent disk is not available, do not treat local SQLite storage as durable production
storage. A PostgreSQL backend and data migration would be a separate implementation task.

## Accounts and roles

Public registration should create an ordinary citizen/user account. Privileged roles must
never be assigned from untrusted browser input. Create or promote the first administrator
only through a supported command or a controlled database procedure that exists in the
deployed version of `app.py`. Do not assume a CLI command is available without checking
`flask --app app.py --help`.

Expected role separation in the incident-reporting design:

| Role | Expected access |
|---|---|
| Citizen / user | Submit and follow their own incident reports |
| Analyst | Review submitted reports, add review notes and confirm classifications |
| Administrator | Manage users, roles and administrative functions |

Every protected route must enforce authorization on the server, not only hide navigation links.

## Post-deployment smoke test

After deployment, verify each route that actually exists in `python -m flask --app app routes`:

1. Open the home page and register a test citizen.
2. Sign in and submit a clearly fictional test incident; do not use real personal or banking data.
3. Confirm the report receives a classification from the incident-report classifier (Astrith, if
   that is the name configured in the application) and is saved to the correct account.
4. Sign in as an analyst and verify that the report appears in the review queue.
5. Confirm that an ordinary citizen cannot access analyst/admin routes.
6. Check the territorial analysis and any separate URL-phishing module, if those routes and
   artifacts are present in the deployed version.
7. Restart the service and confirm that the test account and report remain available.
8. Review Render logs for missing packages, missing model files, database errors and failed imports.

A successful local run does not establish that the public Render deployment is healthy.
Do not claim deployment success until these checks have been completed.
