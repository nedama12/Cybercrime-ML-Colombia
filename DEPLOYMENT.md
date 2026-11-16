# Deployment configuration

The application reads these environment variables:

- `APP_ENV=production` requires an externally supplied secret key.
- `FLASK_SECRET_KEY` must be a private, stable value of at least 32 characters. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it in the deployment secret manager.
- `COOKIE_SECURE=1` enables secure session cookies. Use it when serving the site over HTTPS.
- `USER_DB_PATH` optionally points to an existing SQLite database. Preserve the current database path if account and prediction history must be retained.
- `PORT` optionally sets the HTTP port.

In development, the application creates a local key at `instance/flask_secret_key`. Do not use it as a production secret. Sessions last eight hours; cookies use `HttpOnly` and `SameSite=Lax`, and all write forms require a CSRF token.

Login attempts are limited by email and IP address. Five failed attempts within ten minutes trigger a two-minute wait. The in-memory counter is per process, so each worker has a separate counter.

The Render start command is `gunicorn app:app` (also declared in `Procfile`); build with `pip install -r requirements.txt`. The Flask prediction page exposes Cybercrime Analysis and Phishing Detection as separate modules. Deploy `models/phishing_detector.joblib` and `models/phishing_detector_info.json` with the application to enable the phishing form. The large random forest artifact is tracked through Git LFS; verify the Render checkout has hydrated LFS content. The phishing model only analyzes URL text; it does not fetch submitted sites. Train it from the original CSV with `python -m src.train_phishing --data "path\to\PhiUSIIL_Phishing_URL_Dataset.csv"`.

## Accounts, roles, and first administrator

Public registration always creates a `user`. To establish the initial administrator, create the account normally, then open a trusted local or Render shell and run:

```powershell
flask --app app.py promote-admin admin@example.com
```

The command promotes only an existing account. Admins can assign the `analyst` or `user` role and suspend/reactivate accounts at **User Administration**. Analysis pages and report exports require analyst/admin access. Users can view only their own prediction history and incident records.

## Persistent storage on Render

The current backend is SQLite. SQLite files stored on a Render web service's default filesystem are ephemeral and can be lost on replacement/redeploy. If the service plan supports a persistent disk, mount it (for example at `/var/data`) and set `USER_DB_PATH=/var/data/cybercrime.sqlite3`; preserve and back up that disk when redeploying. This path and disk behavior have not been tested against the live service. If a persistent disk is unavailable, PostgreSQL support and a data migration must be implemented before relying on durable production accounts, incident records, or histories. Do not set `USER_DB_PATH` to an ephemeral path and assume it is durable.

After deploying, verify `/`, registration/login, `/assistant`, analyst-only `/territorial-analysis`, phishing and crime predictions, `/incidents`, and analyst/admin `/reports`. Confirm the admin bootstrap command, model loading, LFS artifacts, session cookie settings, and a database record surviving a service restart. Production could not be reached from the development environment during this implementation; local tests do not establish that Render is healthy.
