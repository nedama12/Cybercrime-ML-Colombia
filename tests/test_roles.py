import pytest

from cyberapp.models import Role, User

PUBLIC = ["/", "/phases/business-data-understanding", "/phases/model-evaluation", "/healthz"]
# endpoint -> roles allowed
PROTECTED = {
    "/dashboard": {"reporter", "analyst", "admin"},
    "/cases/": {"reporter", "analyst", "admin"},
    "/cases/new": {"reporter", "analyst", "admin"},
    "/feedback/new": {"reporter", "analyst", "admin"},
    "/predictions/check": {"analyst", "admin"},
    "/predictions/": {"analyst", "admin"},
    "/reports/": {"analyst", "admin"},
    "/reports/export/cases.csv": {"analyst", "admin"},
    "/model": {"analyst", "admin"},
    "/monitoring/": {"admin"},
    "/admin/users": {"admin"},
    "/feedback/manage": {"admin"},
}


@pytest.mark.parametrize("url", PUBLIC)
def test_public_pages(app, url):
    assert app.test_client().get(url).status_code == 200


@pytest.mark.parametrize("url", PROTECTED)
def test_anonymous_users_are_sent_to_login(app, url):
    response = app.test_client().get(url)
    assert response.status_code == 302 and "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize("username", ["reporter", "analyst", "admin"])
@pytest.mark.parametrize("url,allowed", PROTECTED.items())
def test_each_role_only_reaches_its_functions(login, username, url, allowed):
    status = login(username).get(url).status_code
    assert status == (200 if username in allowed else 403)


def test_admin_cannot_remove_own_admin_role(app, login):
    admin = User.query.filter_by(username="admin").one()
    response = login("admin").post(f"/admin/users/{admin.id}", data={"role": "reporter", "active": "y"},
                                   follow_redirects=True)
    assert b"cannot remove your own administrator access" in response.data
    assert User.query.filter_by(username="admin").one().role == Role.ADMIN


def test_admin_promotes_user(app, login):
    target = User.query.filter_by(username="other").one()
    login("admin").post(f"/admin/users/{target.id}", data={"role": "analyst", "active": "y"})
    assert User.query.filter_by(username="other").one().role == Role.ANALYST
