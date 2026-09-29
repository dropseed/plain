from app.users.models import User
from plain.auth.test import login_client
from plain.testing import Client


def make_admin_client() -> Client:
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    login_client(client, user)
    return client
