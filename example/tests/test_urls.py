from app.contacts.models import ContactSubmission
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


def test_contact_schema_page_renders(db):
    response = Client().get("/contacts/schema")
    assert response.status_code == 200
    assert "Contact us" in response.content.decode()


def test_contact_schema_valid_submission(db):
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "Ada",
            "email": "ada@example.com",
            "subject": "general",
            "message": "This is a long enough message.",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/contacts/schema/success"
    assert ContactSubmission.query.filter(email="ada@example.com").exists()


def test_contact_schema_invalid_rerenders(db):
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "A",  # below min_length
            "email": "not-an-email",
            "subject": "general",
            "message": "short",  # below min_length
        },
    )
    assert response.status_code == 200
    assert "field-error" in response.content.decode()
    assert ContactSubmission.query.count() == 0


def test_contact_schema_check_runs(db):
    # check() cross-field rule: a bug report needs 30+ characters.
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "Ada",
            "email": "ada@example.com",
            "subject": "bug",
            "message": "Too short for a bug.",
        },
    )
    assert response.status_code == 200
    assert "at least 30 characters" in response.content.decode()
    assert ContactSubmission.query.count() == 0
