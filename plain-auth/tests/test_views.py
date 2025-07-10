from plain.auth import get_user_model
from plain.test import Client


def test_login_required_redirect(db):
    client = Client()
    response = client.get("/protected/")
    assert response.status_code == 302
    assert response.url == "/login/?next=/protected/"


def test_view_without_login_required(db):
    client = Client()
    response = client.get("/open/")
    assert response.status_code == 200
    assert response.content == b"open"
    assert response.headers["Cache-Control"] == "private"


def test_admin_required(db):
    client = Client()
    # login required first
    assert client.get("/admin/").status_code == 302

    user = get_user_model().objects.create(username="user")
    client.force_login(user)
    # not admin -> 404
    assert client.get("/admin/").status_code == 404

    user.is_admin = True
    user.save()
    # now admin -> success
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert resp.content == b"admin"


def test_no_login_url_forbidden(db):
    client = Client()
    response = client.get("/nolink/")
    assert response.status_code == 403
