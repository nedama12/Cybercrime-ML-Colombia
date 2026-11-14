"""WSGI entry point.

Local:   flask --app app run --debug
Render:  gunicorn app:app
"""
from cyberapp import create_app

app = create_app()
