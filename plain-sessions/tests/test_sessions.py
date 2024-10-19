from plain.sessions.models import Session


def test_session_created(db, client):
    assert Session.objects.count() == 0

    response = client.get("/")

    assert response.status_code == 200

    assert Session.objects.count() == 1
