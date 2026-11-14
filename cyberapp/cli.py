"""Command line tasks: flask --app app <command>."""
import click

from .extensions import db
from .models import Role, User


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
