"""Public pages: PGC project overview and CRISP-ML documentation."""
from flask import Blueprint, render_template

bp = Blueprint("docs", __name__)


@bp.route("/")
def home():
    return render_template("index.html")
