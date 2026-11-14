# Configuración segura del despliegue

La aplicación lee estas variables de entorno:

- `APP_ENV=production`: exige que se configure una clave secreta externa.
- `FLASK_SECRET_KEY`: secreto privado de al menos 32 caracteres. Genéralo, por ejemplo, con `python -c "import secrets; print(secrets.token_urlsafe(48))"` y guárdalo en el gestor de secretos del despliegue.
- `COOKIE_SECURE=1`: activa cookies de sesión seguras; úsalo cuando el sitio se sirva bajo HTTPS.
- `USER_DB_PATH`: opcional. Ruta al archivo SQLite existente si no se usa `instance/cybercrime.sqlite3`. No apuntes a un archivo nuevo en producción si necesitas conservar los datos actuales.
- `PORT`: puerto HTTP, opcional.

En desarrollo se mantiene la generación de una clave local en `instance/flask_secret_key`. No reutilices esa clave como secreto de producción. La aplicación conserva sesiones de ocho horas, con cookies `HttpOnly` y `SameSite=Lax`; los formularios de escritura requieren token CSRF.

Los intentos de login se limitan por correo e IP: cinco fallos dentro de diez minutos activan una espera de dos minutos. El contador es en memoria por proceso, por lo que en despliegues con varios workers cada worker mantiene su propio contador.
