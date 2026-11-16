# Deployment configuration

The application reads these environment variables:

- `APP_ENV=production` requires an externally supplied secret key.
- `FLASK_SECRET_KEY` must be a private, stable value of at least 32 characters. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it in the deployment secret manager.
- `COOKIE_SECURE=1` enables secure session cookies. Use it when serving the site over HTTPS.
- `USER_DB_PATH` optionally points to an existing SQLite database. Preserve the current database path if account and prediction history must be retained.
- `PORT` optionally sets the HTTP port.

In development, the application creates a local key at `instance/flask_secret_key`. Do not use it as a production secret. Sessions last eight hours; cookies use `HttpOnly` and `SameSite=Lax`, and all write forms require a CSRF token.

Login attempts are limited by email and IP address. Five failed attempts within ten minutes trigger a two-minute wait. The in-memory counter is per process, so each worker has a separate counter.

The Flask prediction page exposes Cybercrime Analysis and Phishing Detection as separate modules. Deploy `models/phishing_detector.joblib` and `models/phishing_detector_info.json` with the application to enable the phishing form. This model only analyzes URL text; it does not fetch submitted sites. Train it from the original CSV with `python -m src.train_phishing --data "path\to\PhiUSIIL_Phishing_URL_Dataset.csv"`.
