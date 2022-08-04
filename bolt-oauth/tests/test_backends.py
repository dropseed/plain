import pytest
from django.contrib.auth.models import AnonymousUser

from forgeoauth.providers import OAuthProvider, OAuthToken, OAuthUser


class DummyProvider(OAuthProvider):
    def get_oauth_token(self, *, code, request):
        return OAuthToken(
            access_token="dummy_token",
        )

    def get_oauth_user(self, *, oauth_token):
        return OAuthUser(
            id="dummy_user_id",
            username="dummy_username",
            email="dummy@example.com",
        )

    def check_request_state(self, *, request):
        """Don't check the state"""
        return


@pytest.mark.django_db
def test_single_backend(client, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_backends.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }
    settings.AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
    ]

    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.context["user"].is_authenticated


@pytest.mark.django_db
def test_multiple_backends(client, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_backends.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }
    settings.AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.context["user"].is_authenticated
