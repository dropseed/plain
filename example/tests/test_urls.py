from app.users.models import User

from plain.test import Client


def test_admin_access(db):
    client = Client()

    # Login required
    assert client.get("/admin").status_code == 302

    user = User.query.create(email="admin@example.com", password="strongpass1")
    client.force_login(user)

    # Not admin yet
    assert client.get("/admin").status_code == 404

    user.is_admin = True
    user.save()

    # Now admin
    assert client.get("/admin").status_code in {200, 302}


def test_login_link_page_renders(db):
    response = Client().get("/login-link")
    assert response.status_code == 200
    assert "Email me a link" in response.content.decode()


def test_login_link_invalid_email_rerenders_with_error(db):
    response = Client().post("/login-link", data={"email": "not-an-email"})
    # Re-renders the form (no redirect) with the field error visible.
    assert response.status_code == 200
    assert "field-error" in response.content.decode()


def test_login_link_valid_email_redirects(db):
    User.query.create(email="member@example.com", password="strongpass1")
    response = Client().post("/login-link", data={"email": "member@example.com"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/loginlink/sent"


def test_login_link_unknown_email_still_redirects(db):
    # No account enumeration — an unknown email looks the same as a known one.
    response = Client().post("/login-link", data={"email": "nobody@example.com"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/loginlink/sent"
