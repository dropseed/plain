import datetime

import pytest
from app.users.models import User

from plain.oauth.models import OAuthConnection
from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser
from plain.test import Client


class DummyProvider(OAuthProvider):
    authorization_url = "https://example.com/oauth/authorize"

    def generate_state(self) -> str:
        return "dummy_state"

    def refresh_oauth_token(self, *, oauth_token: OAuthToken) -> OAuthToken:
        return OAuthToken(
            access_token="refreshed_dummy_access_token",
            refresh_token="refreshed_dummy_refresh_token",
            access_token_expires_at=datetime.datetime(
                2029, 1, 1, 0, 0, tzinfo=datetime.UTC
            ),
            refresh_token_expires_at=datetime.datetime(
                2029, 1, 2, 0, 0, tzinfo=datetime.UTC
            ),
        )

    def get_oauth_token(self, *, code, request) -> OAuthToken:
        return OAuthToken(
            access_token="dummy_access_token",
            refresh_token="dummy_refresh_token",
            access_token_expires_at=datetime.datetime(
                2020, 1, 1, 0, 0, tzinfo=datetime.UTC
            ),
            refresh_token_expires_at=datetime.datetime(
                2020, 1, 2, 0, 0, tzinfo=datetime.UTC
            ),
        )

    def get_oauth_user(self, *, oauth_token: OAuthToken) -> OAuthUser:
        return OAuthUser(
            provider_id="dummy_id",
            user_model_fields={
                "email": "dummy@example.com",
                "username": "dummy_username",
            },
        )


def test_dummy_signup(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }

    client = Client()

    assert User.query.count() == 0
    assert OAuthConnection.query.count() == 0

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello dummy_username!\n" in response.content

    # Check the user and connection that was created
    user = response.user
    assert user.username == "dummy_username"
    assert user.email == "dummy@example.com"
    connections = user.oauth_connections.query.all()
    assert len(connections) == 1
    assert connections[0].provider_key == "dummy"
    assert connections[0].provider_user_id == "dummy_id"
    assert connections[0].access_token == "dummy_access_token"
    assert connections[0].refresh_token == "dummy_refresh_token"
    assert connections[0].access_token_expires_at == datetime.datetime(
        2020, 1, 1, 0, 0, tzinfo=datetime.UTC
    )
    assert connections[0].refresh_token_expires_at == datetime.datetime(
        2020, 1, 2, 0, 0, tzinfo=datetime.UTC
    )

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 1


def test_dummy_login_connection(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }

    client = Client()

    assert User.query.count() == 0
    assert OAuthConnection.query.count() == 0

    # Create a user
    user = User.query.create(username="dummy_username", email="dummy@example.com")
    OAuthConnection.query.create(
        user=user,
        provider_key="dummy",
        provider_user_id="dummy_id",
        access_token="dummy_access_token",
        refresh_token="dummy_refresh_token",
        access_token_expires_at=datetime.datetime(
            2020, 1, 1, 0, 0, tzinfo=datetime.UTC
        ),
        refresh_token_expires_at=datetime.datetime(
            2020, 1, 2, 0, 0, tzinfo=datetime.UTC
        ),
    )

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 1

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello dummy_username!\n" in response.content

    # Check the user and connection that was created
    user = response.user
    assert user.username == "dummy_username"
    assert user.email == "dummy@example.com"
    connections = user.oauth_connections.query.all()
    assert len(connections) == 1
    assert connections[0].provider_key == "dummy"
    assert connections[0].provider_user_id == "dummy_id"
    assert connections[0].access_token == "dummy_access_token"
    assert connections[0].refresh_token == "dummy_refresh_token"
    assert connections[0].access_token_expires_at == datetime.datetime(
        2020, 1, 1, 0, 0, tzinfo=datetime.UTC
    )
    assert connections[0].refresh_token_expires_at == datetime.datetime(
        2020, 1, 2, 0, 0, tzinfo=datetime.UTC
    )

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 1


def test_dummy_login_without_connection(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }

    client = Client()

    assert User.query.count() == 0
    assert OAuthConnection.query.count() == 0

    # Create a user
    User.query.create(username="dummy_username", email="dummy@example.com")

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 0

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback?code=test_code&state=dummy_state")
    assert response.status_code == 400
    assert b"OAuth Error" in response.content


def test_dummy_connect(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }

    client = Client()

    assert User.query.count() == 0
    assert OAuthConnection.query.count() == 0

    # Create a user
    user = User.query.create(username="dummy_username", email="dummy@example.com")

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 0

    client.force_login(user)

    response = client.post("/oauth/dummy/connect")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")

    # Check the user and connection that was created
    user = response.user
    connections = user.oauth_connections.query.all()
    assert len(connections) == 1
    assert connections[0].provider_key == "dummy"
    assert connections[0].provider_user_id == "dummy_id"
    assert connections[0].access_token == "dummy_access_token"
    assert connections[0].refresh_token == "dummy_refresh_token"
    assert connections[0].access_token_expires_at == datetime.datetime(
        2020, 1, 1, 0, 0, tzinfo=datetime.UTC
    )
    assert connections[0].refresh_token_expires_at == datetime.datetime(
        2020, 1, 2, 0, 0, tzinfo=datetime.UTC
    )

    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 1


def _configure_dummy(settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }


def _make_connection(user, provider_user_id="dummy_id"):
    return OAuthConnection.query.create(
        user=user,
        provider_key="dummy",
        provider_user_id=provider_user_id,
        access_token="dummy_access_token",
        refresh_token="dummy_refresh_token",
    )


def test_dummy_disconnect_removes_own_connection(db, settings):
    _configure_dummy(settings)

    user = User.query.create(username="dummy_username", email="dummy@example.com")
    _make_connection(user)
    _make_connection(user, provider_user_id="dummy_id2")

    client = Client()
    client.force_login(user)

    response = client.post(
        "/oauth/dummy/disconnect", data={"provider_user_id": "dummy_id"}
    )

    assert response.status_code == 302
    assert OAuthConnection.query.filter(user=user).count() == 1
    assert (
        OAuthConnection.query.filter(user=user, provider_user_id="dummy_id").exists()
        is False
    )


def test_dummy_disconnect_cannot_remove_another_users_connection(db, settings):
    """A logged-in user must not be able to disconnect a connection that
    belongs to a different user by supplying its provider_user_id."""
    _configure_dummy(settings)

    victim = User.query.create(username="victim", email="victim@example.com")
    _make_connection(victim, provider_user_id="victim_provider_id")

    attacker = User.query.create(username="attacker", email="attacker@example.com")
    _make_connection(attacker, provider_user_id="attacker_provider_id")

    client = Client()
    client.force_login(attacker)

    # Attacker targets the victim's connection. The user-scoped lookup finds
    # nothing for the attacker, so the request errors instead of deleting.
    with pytest.raises(OAuthConnection.DoesNotExist):
        client.post(
            "/oauth/dummy/disconnect",
            data={"provider_user_id": "victim_provider_id"},
        )

    # The victim's connection is untouched.
    assert OAuthConnection.query.filter(
        user=victim, provider_user_id="victim_provider_id"
    ).exists()


def test_dummy_disconnect_requires_login(db, settings):
    _configure_dummy(settings)

    user = User.query.create(username="dummy_username", email="dummy@example.com")
    _make_connection(user)

    # Not logged in -> redirected to login, connection preserved.
    response = Client().post(
        "/oauth/dummy/disconnect", data={"provider_user_id": "dummy_id"}
    )

    assert response.status_code == 302
    assert "/login" in response.url
    assert OAuthConnection.query.count() == 1


def test_dummy_refresh(db, settings, monkeypatch):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "dummy": {
            "class": "test_providers.DummyProvider",
            "kwargs": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "scope": "dummy_scope",
            },
        }
    }

    user = User.query.create(username="dummy_username", email="dummy@example.com")
    connection = OAuthConnection.query.create(
        user=user,
        provider_key="dummy",
        provider_user_id="dummy_id",
        access_token="dummy_access_token",
        refresh_token="dummy_refresh_token",
        access_token_expires_at=datetime.datetime(
            2020, 1, 1, 0, 0, tzinfo=datetime.UTC
        ),
        refresh_token_expires_at=datetime.datetime(
            2020, 1, 2, 0, 0, tzinfo=datetime.UTC
        ),
    )

    connection.refresh_access_token()
    assert connection.provider_key == "dummy"
    assert connection.provider_user_id == "dummy_id"
    assert connection.access_token == "refreshed_dummy_access_token"
    assert connection.refresh_token == "refreshed_dummy_refresh_token"
    assert connection.access_token_expires_at == datetime.datetime(
        2029, 1, 1, 0, 0, tzinfo=datetime.UTC
    )
    assert connection.refresh_token_expires_at == datetime.datetime(
        2029, 1, 2, 0, 0, tzinfo=datetime.UTC
    )
