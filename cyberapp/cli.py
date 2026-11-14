"""Command line tasks: flask --app app <command>."""
import click

from .extensions import db
from .models import Role, User
from .monitoring import operational_review


def register(app):
    @app.cli.command("init-db")
    def init_db():
        """Create the database tables (safe to run more than once)."""
        db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def create_admin(username, email, password):
        """Create an administrator account. Administrators are only created here, never from the web form."""
        if User.query.filter((User.username == username) | (User.email == email)).first():
            raise click.ClickException("A user with that username or email already exists.")
        user = User(username=username, email=email.lower(), role=Role.ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("monitoring-report")
    @click.option("--days", default=7, show_default=True)
    @click.option("--real-only", is_flag=True, help="Exclude simulated data.")
    def monitoring_report(days, real_only):
        """Print the operational review (evidence for CRISP-ML phase 6)."""
        from .ml.features import load_json
        from .ml.service import get_model_service

        reference = load_json(app.config["MODEL_DIR"] / "reference_stats.json")
        r = operational_review(get_model_service(), reference, days=days, include_simulated=not real_only)
        fmt = lambda v, f="{:.3f}": "-" if v is None else f.format(v)  # noqa: E731
        click.echo(f"Operational review - last {days} days ({'real data only' if real_only else 'includes simulated data'})")
        click.echo(f"Model: ready={r['model']['ready']} version={r['model']['model_version']}")
        click.echo(f"Requests: {r['requests']}  errors: {r['errors']}  error rate: {fmt(r['error_rate'], '{:.2%}')}")
        click.echo(f"Response time p50/p95 (ms): {fmt(r['p50'], '{:.0f}')} / {fmt(r['p95'], '{:.0f}')}")
        click.echo(f"Predictions: {r['predictions']} (simulated: {r['simulated_predictions']})")
        if r["performance"]:
            p = r["performance"]
            click.echo(f"Live performance (n={p['n']}): accuracy={fmt(p['accuracy'])} precision={fmt(p['precision'])} "
                       f"recall={fmt(p['recall'])} f1={fmt(p['f1'])}")
        drifting = [d for d in r["drift"] if d["status"] in ("moderate", "significant")]
        click.echo(f"Features with drift: {', '.join(d['feature'] + '=' + fmt(d['psi']) for d in drifting) or 'none'}")
        for level, message in r["alerts"] or [("ok", "No alert rule triggered.")]:
            click.echo(f"[{level.upper()}] {message}")

    @app.cli.command("seed-demo")
    @click.option("--cases", default=40, show_default=True)
    @click.option("--days", default=14, show_default=True)
    @click.password_option(help="Password for the demo_reporter and demo_analyst accounts.")
    def seed_demo(cases, days, password):
        """Create SIMULATED cases and predictions for demonstrations and the monitoring test."""
        from .demo import seed

        result = seed(password, cases=cases, days=days)
        click.echo(f"Simulated data created: {result['cases']} cases, {result['classified']} classified, "
                   f"{result['closed']} closed (model ready: {result['model_ready']}).")
        click.echo("Accounts: demo_reporter, demo_analyst. Every record is labeled SIMULATED.")

    @app.cli.command("clear-demo")
    def clear_demo():
        """Delete every SIMULATED record."""
        from .demo import clear

        cases, predictions = clear()
        click.echo(f"Deleted {cases} simulated cases and {predictions} simulated predictions.")
