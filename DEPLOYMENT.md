# Secure deployment settings

The application reads these environment variables:

- `APP_ENV=production`: requires an external secret key.
- `FLASK_SECRET_KEY`: private secret of at least 32 characters. Generate it with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it in the hosting
  secret manager (on Render, `render.yaml` generates it).
- `COOKIE_SECURE=1`: secure session cookies; use it when the site is served over HTTPS.
- `ANALYST_EMAILS`: comma-separated emails that receive the analyst role when they register.
- `ADMIN_EMAILS`: comma-separated emails that receive the administrator role when they register
  (use it once to create the first administrator; afterwards roles are managed in
  **Admin > Users and roles**).
- `USER_DB_PATH`: path to the SQLite file. On Render it points to the persistent disk
  (`/var/data/cybercrime.sqlite3`); without a disk, accounts and reports are lost on every
  restart or redeploy.
- `BEHIND_PROXY=1`: trust one proxy hop (Render) so the login rate limit sees the real client IP.
- `PORT`: optional HTTP port.

See `.env.example` for a complete example without secrets.

## Render

`render.yaml` defines the web service: `pip install -r requirements.txt`, `gunicorn app:app`,
the health check `/healthz` and a 1 GB persistent disk mounted at `/var/data` for the database.
Persistent disks require a paid instance (`plan: starter`); with `plan: free` the service works
but the database is reset on every restart.

1. In Render choose **New > Blueprint**, select the repository and confirm the plan.
2. Set `ADMIN_EMAILS` (and optionally `ANALYST_EMAILS`) in the service environment.
3. After the first deploy open `/healthz`: it must answer `{"status": "ok", "database": "ok", ...}`.
4. Register the administrator account with the email in `ADMIN_EMAILS`, then create the test
   accounts from **Admin > Users and roles** or with the shell command
   `flask --app app create-user --role analyst` (the password is asked privately).

### Database

The schema is created and migrated automatically when the application starts (`create_schema`
in `app.py`): new tables and columns are added without deleting data. Tables: `users`,
`incident_reports`, `report_events`, `inferences`, `support_tickets`, `model_versions`,
`request_log`, `operational_reviews`, `audit_log` and `login_attempts`.

Backup and restore:

```bash
flask --app app backup-db /var/data/backup-$(date +%F).sqlite3   # online copy
# restore: stop the service, copy the backup over USER_DB_PATH, start the service
```

### Smoke test after each deployment

1. `/healthz` answers `ok` with the expected model version.
2. Register a citizen, send a report, see the result, edit it and check the report history.
3. Log in as analyst: the report is in **Review**, close it with a confirmed category.
4. Log in as citizen again: the status is Closed; `/review` and `/admin/users` answer 403.
5. Restart the service from the Render dashboard and log in again: accounts, reports and the
   inference history are still there (persistence).
6. As administrator open **Operations**: the requests, inferences and response times of the
   smoke test appear; record the operational review.

## Roles

| Role | How it is granted | Access |
|---|---|---|
| Citizen | Default for every registration | Own reports (create, read, edit, delete while received), territorial analysis, support requests |
| Analyst | Administrator, `ANALYST_EMAILS` or `flask set-role EMAIL analyst` | Review queue, indicators, CSV export, inference history, support desk |
| Administrator | `ADMIN_EMAILS` or `flask set-role EMAIL admin` | Everything above plus users and roles, report deletion, operations and model registry |

The role is never taken from the browser. Every operational route checks it on the server and
answers 403 when it is not allowed. Test accounts for each role are delivered privately to the
instructor; passwords are never stored in the repository.

Before publishing, check that the official channels shown after a report (A Denunciar, CAI
Virtual, line 122, line 123, SIC and ColCERT) are still current.

## Security notes

In development a local key is generated in `instance/flask_secret_key`; never reuse it in
production.

Authentication:

- Passwords are stored only as **scrypt** hashes (Werkzeug). Older hashes are upgraded to scrypt
  on the next successful login. Passwords need 8-128 characters with letters and numbers, and
  common passwords or passwords containing the email or name are rejected.
- A report can only be sent by a logged-in user; anonymous visitors are sent to log in or
  register and come back to the report form afterwards.
- Login answers "Incorrect email or password" in every case and always checks a hash, so it
  does not reveal which emails exist.
- Failed attempts are stored in the `login_attempts` table, so the limit works with several
  gunicorn workers: 5 failures for one email from one IP in 10 minutes, or 20 failures from one
  IP, block new attempts for 2 minutes (HTTP 429).
- Each login starts a new session (no session fixation). Sessions last eight hours of activity,
  with `HttpOnly`, `SameSite=Lax` and, in production, `Secure` cookies.
- Changing the password in **Account** signs out every other device (`session_version`).
- Every form that writes data requires a CSRF token; redirects after login only go to paths of
  this site; private pages are sent with `Cache-Control: no-store`, `X-Frame-Options: DENY` and
  `X-Content-Type-Options: nosniff`.
