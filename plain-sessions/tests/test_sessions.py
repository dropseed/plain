from plain.sessions.models import Session
from plain.test import Client


def test_session_created(db):
    assert Session.objects.count() == 0

    response = Client().get("/")

    assert response.status_code == 200

    assert Session.objects.count() == 1
