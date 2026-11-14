"""Cybercrime Analytics Colombia - Flask application factory."""
import logging

from flask import Flask

from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class)
    _configure_logging(app)

    from .blueprints import docs

    app.register_blueprint(docs.bp)
    return app


def _configure_logging(app):
    """Log to stdout so Render (or any host) captures the application log."""
    if not app.logger.handlers or app.debug:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    app.logger.setLevel(logging.INFO)
