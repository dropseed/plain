import datetime

from plain.auth import get_user_model
from plain.oauth.models import OAuthConnection
from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser


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
            id="dummy_id",
            email="dummy@example.com",
            username="dummy_username",
        )


def test_dummy_signup(db, client, settings):
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

    assert get_user_model().objects.count() == 0
    assert OAuthConnection.objects.count() == 0

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login/?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login/")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback%2F&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
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
    connections = user.oauth_connections.all()
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

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 1


def test_dummy_login_connection(db, client, settings):
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

    assert get_user_model().objects.count() == 0
    assert OAuthConnection.objects.count() == 0

    # Create a user
    user = get_user_model().objects.create(
        username="dummy_username", email="dummy@example.com"
    )
    OAuthConnection.objects.create(
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

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 1

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login/?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login/")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback%2F&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
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
    connections = user.oauth_connections.all()
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

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 1


def test_dummy_login_without_connection(db, client, settings):
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

    assert get_user_model().objects.count() == 0
    assert OAuthConnection.objects.count() == 0

    # Create a user
    get_user_model().objects.create(
        username="dummy_username", email="dummy@example.com"
    )

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 0

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login/?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/dummy/login/")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback%2F&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 400
    assert b"OAuth Error" in response.content


def test_dummy_connect(db, client, settings):
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

    assert get_user_model().objects.count() == 0
    assert OAuthConnection.objects.count() == 0

    # Create a user
    user = get_user_model().objects.create(
        username="dummy_username", email="dummy@example.com"
    )

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 0

    client.force_login(user)

    response = client.post("/oauth/dummy/connect/")
    assert response.status_code == 302
    assert (
        response.url
        == "https://example.com/oauth/authorize?client_id=dummy_client_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fdummy%2Fcallback%2F&response_type=code&scope=dummy_scope&state=dummy_state"
    )

    # Provider redirects to the callback url
    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")

    # Check the user and connection that was created
    user = response.user
    connections = user.oauth_connections.all()
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

    assert get_user_model().objects.count() == 1
    assert OAuthConnection.objects.count() == 1


# def test_dummy_disconnect_to_password(db, client, settings):
#     settings.OAUTH_LOGIN_PROVIDERS = {
#         "dummy": {
#             "class": "test_providers.DummyProvider",
#             "kwargs": {
#                 "client_id": "dummy_client_id",
#                 "client_secret": "dummy_client_secret",
#                 "scope": "dummy_scope",
#             },
#         }
#     }

#     assert get_user_model().objects.count() == 0
#     assert OAuthConnection.objects.count() == 0

#     # Create a user
#     user = get_user_model().objects.create(
#         username="dummy_username", email="dummy@example.com", password="dummy_password"
#     )
#     OAuthConnection.objects.create(
#         user=user,
#         provider_key="dummy",
#         provider_user_id="dummy_id",
#         access_token="dummy_access_token",
#         refresh_token="dummy_refresh_token",
#         access_token_expires_at=datetime.datetime(
#             2020, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#         refresh_token_expires_at=datetime.datetime(
#             2020, 1, 2, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#     )

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 1

#     client.force_login(user)

#     # Raises a BadRequest error - can't disconnect the last connection without a password
#     response = client.post(
#         "/oauth/dummy/disconnect/", data={"provider_user_id": "dummy_id"}
#     )
#     assert response.status_code == 302
#     assert response.url == "/"

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 0


# def test_dummy_disconnect_to_connection(db, client, settings):
#     settings.OAUTH_LOGIN_PROVIDERS = {
#         "dummy": {
#             "class": "test_providers.DummyProvider",
#             "kwargs": {
#                 "client_id": "dummy_client_id",
#                 "client_secret": "dummy_client_secret",
#                 "scope": "dummy_scope",
#             },
#         }
#     }

#     assert get_user_model().objects.count() == 0
#     assert OAuthConnection.objects.count() == 0

#     # Create a user
#     user = get_user_model().objects.create(
#         username="dummy_username", email="dummy@example.com"
#     )
#     OAuthConnection.objects.create(
#         user=user,
#         provider_key="dummy",
#         provider_user_id="dummy_id",
#         access_token="dummy_access_token",
#         refresh_token="dummy_refresh_token",
#         access_token_expires_at=datetime.datetime(
#             2020, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#         refresh_token_expires_at=datetime.datetime(
#             2020, 1, 2, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#     )
#     OAuthConnection.objects.create(
#         user=user,
#         provider_key="dummy",
#         provider_user_id="dummy_id2",
#         access_token="dummy_access_token",
#         refresh_token="dummy_refresh_token",
#         access_token_expires_at=datetime.datetime(
#             2020, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#         refresh_token_expires_at=datetime.datetime(
#             2020, 1, 2, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#     )

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 2

#     client.force_login(user)

#     # Raises a BadRequest error - can't disconnect the last connection without a password
#     response = client.post(
#         "/oauth/dummy/disconnect/", data={"provider_user_id": "dummy_id"}
#     )
#     assert response.status_code == 302
#     assert response.url == "/"

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 1


# def test_dummy_disconnect_last(db, client, settings):
#     settings.OAUTH_LOGIN_PROVIDERS = {
#         "dummy": {
#             "class": "test_providers.DummyProvider",
#             "kwargs": {
#                 "client_id": "dummy_client_id",
#                 "client_secret": "dummy_client_secret",
#                 "scope": "dummy_scope",
#             },
#         }
#     }

#     assert get_user_model().objects.count() == 0
#     assert OAuthConnection.objects.count() == 0

#     # Create a user
#     user = get_user_model().objects.create(
#         username="dummy_username", email="dummy@example.com"
#     )
#     OAuthConnection.objects.create(
#         user=user,
#         provider_key="dummy",
#         provider_user_id="dummy_id",
#         access_token="dummy_access_token",
#         refresh_token="dummy_refresh_token",
#         access_token_expires_at=datetime.datetime(
#             2020, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#         refresh_token_expires_at=datetime.datetime(
#             2020, 1, 2, 0, 0, tzinfo=datetime.timezone.utc
#         ),
#     )

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 1

#     client.force_login(user)

#     # Raises a BadRequest error - can't disconnect the last connection without a password
#     response = client.post(
#         "/oauth/dummy/disconnect/", data={"provider_user_id": "dummy_id"}
#     )
#     assert response.status_code == 400
#     assert response.templates[0].name == "oauth/error.html"

#     assert get_user_model().objects.count() == 1
#     assert OAuthConnection.objects.count() == 1


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

    user = get_user_model().objects.create(
        username="dummy_username", email="dummy@example.com"
    )
    connection = OAuthConnection.objects.create(
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
