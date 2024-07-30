from plain.sessions.models import Session


def test_session_created(db, client):
    assert Session.objects.count() == 0

    client.get("/")

    assert Session.objects.count() == 1
