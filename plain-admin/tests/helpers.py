from app.users.models import User

from plain.test import Client


def make_admin_client() -> Client:
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    client.force_login(user)
    return client
