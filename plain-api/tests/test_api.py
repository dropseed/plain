from plain.test import Client


def test_api_view():
    client = Client()
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, world!"}


def test_versioned_api_view():
    client = Client()
    response = client.post(
        "/test-versioned",
        headers={"API-Version": "v2"},
        data={"name": "Dave"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, Dave!"}

    response = client.post(
        "/test-versioned",
        headers={"API-Version": "v1"},
        data={"to": "Dave"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {"msg": "Hello, Dave!"}
