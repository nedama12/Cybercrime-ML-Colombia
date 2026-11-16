# Secure deployment settings

The application reads these environment variables:

- `APP_ENV=production`: requires an external secret key.
- `FLASK_SECRET_KEY`: private secret of at least 32 characters. Generate it with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it in the hosting
  secret manager (on Render, `render.yaml` generates it).
- `COOKIE_SECURE=1`: secure session cookies; use it when the site is served over HTTPS.
- `ANALYST_EMAILS`: comma-separated emails that receive the analyst role when they register.
- `USER_DB_PATH`: optional path to the SQLite file. On Render, point it to a persistent disk
  (for example `/var/data/cybercrime.sqlite3`); without a disk, accounts and reports are lost on
  every redeploy.
- `BEHIND_PROXY=1`: trust one proxy hop (Render) so the login rate limit sees the real client IP.
- `PORT`: optional HTTP port.

## Render

`render.yaml` defines the web service: `pip install -r requirements.txt` and
`gunicorn app:app`. Create it from the dashboard with **New > Blueprint**, then set
`ANALYST_EMAILS` and, if available, a persistent disk for `USER_DB_PATH`.

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
