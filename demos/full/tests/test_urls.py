from app.users.models import User

from plain.test import Client


def test_admin_access(db):
    client = Client()

    # Login required
    assert client.get("/admin/").status_code == 302

    user = User.query.create(email="admin@example.com", password="strongpass1")
    client.force_login(user)

    # Not admin yet
    assert client.get("/admin/").status_code == 404

    user.is_admin = True
    user.save()

    # Now admin
    assert client.get("/admin/").status_code in {200, 302}
