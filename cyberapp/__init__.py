"""Cybercrime Analytics Colombia - Flask application factory."""
import logging
from pathlib import Path

from flask import Flask

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

    from .blueprints import auth, docs

    app.register_blueprint(docs.bp)
    app.register_blueprint(auth.bp)

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
