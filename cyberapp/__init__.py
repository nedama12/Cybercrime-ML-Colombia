"""Cybercrime Analytics Colombia - Flask application factory."""
import logging
from pathlib import Path

from flask import Flask, render_template

from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class)
    _configure_logging(app)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    from .extensions import csrf, db, login_manager

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    from . import models  # noqa: F401  (registers the tables)

    from .ml.service import init_model_service

    init_model_service(app)

    from .blueprints import account, admin, auth, cases, docs, model, monitoring, predictions, reports

    for module in (docs, auth, account, admin, model, cases, predictions, reports, monitoring):
        app.register_blueprint(module.bp)
    _register_error_handlers(app)

    from .monitoring import init_request_logging

    init_request_logging(app)

    @app.context_processor
    def inject_project():
        from .content import PHASES, PROJECT
        return {"project": PROJECT, "phases": PHASES}

    from . import cli

    cli.register(app)
    return app


def _configure_logging(app):
    """Log to stdout so Render (or any host) captures the application log."""
    if not app.logger.handlers or app.debug:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    app.logger.setLevel(logging.INFO)


ERRORS = {
    403: ("Access denied", "Your role does not have permission to open this page."),
    404: ("Page not found", "The page you are looking for does not exist."),
    500: ("Something went wrong", "The error was logged. Please try again or report the incident."),
}


def _register_error_handlers(app):
    def handler(error):
        code = getattr(error, "code", 500) or 500
        title, message = ERRORS.get(code, ERRORS[500])
        return render_template("errors/error.html", code=code, title=title, message=message), code

    for code in ERRORS:
        app.register_error_handler(code, handler)
