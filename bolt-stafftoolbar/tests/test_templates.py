import pytest
from django.contrib.auth.models import User


def test_logged_out(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="stafftoolbar"' not in response.content


@pytest.mark.django_db
def test_staff_logged_in(client):
    User.objects.create_user(username="testuser", password="testuser", is_staff=True)
    client.login(username="testuser", password="testuser")
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="stafftoolbar"' in response.content


@pytest.mark.django_db
def test_normal_logged_in(client):
    User.objects.create_user(username="testuser", password="testuser")
    client.login(username="testuser", password="testuser")
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="stafftoolbar"' not in response.content
