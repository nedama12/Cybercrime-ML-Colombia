from cyberapp.extensions import db
from cyberapp.models import Role, User

from .conftest import PASSWORD


def test_register_always_creates_reporter_even_if_role_is_posted(app):
    client = app.test_client()
    response = client.post("/auth/register", data={
        "username": "mallory", "email": "mallory@example.com", "password": "abc12345",
        "confirm": "abc12345", "role": "admin"})
    assert response.status_code == 302
    user = User.query.filter_by(username="mallory").one()
    assert user.role == Role.REPORTER


def test_password_is_stored_as_salted_hash(app):
    user = User.query.filter_by(username="reporter").one()
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith(("scrypt:", "pbkdf2:"))
    assert user.check_password(PASSWORD) and not user.check_password("wrong")


def test_register_rejects_weak_password_and_duplicates(app):
    client = app.test_client()
    weak = client.post("/auth/register", data={"username": "bob", "email": "bob@example.com",
                                               "password": "abcdefgh", "confirm": "abcdefgh"})
    assert b"at least one letter and one number" in weak.data
    dup = client.post("/auth/register", data={"username": "reporter", "email": "new@example.com",
                                              "password": "abc12345", "confirm": "abc12345"})
    assert b"already taken" in dup.data


def test_login_logout(app):
    client = app.test_client()
    assert client.post("/auth/login", data={"username": "reporter", "password": PASSWORD}).status_code == 302
    assert client.get("/dashboard").status_code == 200
    assert client.post("/auth/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302  # back to the login page


def test_account_is_locked_after_repeated_failures(app):
    client = app.test_client()
    for _ in range(5):
        client.post("/auth/login", data={"username": "reporter", "password": "bad"})
    response = client.post("/auth/login", data={"username": "reporter", "password": PASSWORD},
                           follow_redirects=True)
    assert b"Too many failed attempts" in response.data


def test_deactivated_user_cannot_log_in(app):
    user = User.query.filter_by(username="reporter").one()
    user.active = False
    db.session.commit()
    response = app.test_client().post("/auth/login", data={"username": "reporter", "password": PASSWORD},
                                      follow_redirects=True)
    assert b"deactivated" in response.data


def test_login_does_not_redirect_to_external_sites(app):
    client = app.test_client()
    response = client.post("/auth/login?next=https://evil.example.com",
                           data={"username": "reporter", "password": PASSWORD})
    assert response.headers["Location"] == "/dashboard"
