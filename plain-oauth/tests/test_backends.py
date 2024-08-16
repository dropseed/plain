from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser


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


def test_single_backend(db, client, settings):
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

    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.user


def test_multiple_backends(db, client, settings):
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

    response = client.get("/oauth/dummy/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.user
