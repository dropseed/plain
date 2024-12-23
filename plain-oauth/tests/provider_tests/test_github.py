from tests.providers.github import GitHubOAuthProvider

from plain.oauth.providers import OAuthToken, OAuthUser


class DummyGitHubOAuthProvider(GitHubOAuthProvider):
    def generate_state(self) -> str:
        return "dummy_state"

    def get_oauth_token(self, code, request):
        return OAuthToken(access_token="gho_key")

    def get_oauth_user(self, oauth_token):
        return OAuthUser(
            id="99",
            username="userone",
            email="user@example.com",
        )


def test_github_provider(db, client, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "github": {
            "class": "provider_tests.test_github.DummyGitHubOAuthProvider",
            "kwargs": {
                "client_id": "test_id",
                "client_secret": "test_secret",
                "scope": "user",
            },
        }
    }

    # Login required for this view
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/login/?next=/"

    # User clicks the login link (form submit)
    response = client.post("/oauth/github/login/")
    assert response.status_code == 302
    assert (
        response.url
        == "https://github.com/login/oauth/authorize?client_id=test_id&redirect_uri=https%3A%2F%2Ftestserver%2Foauth%2Fgithub%2Fcallback%2F&response_type=code&scope=user&state=dummy_state"
    )

    # GitHub redirects to the callback url
    response = client.get("/oauth/github/callback/?code=test_code&state=dummy_state")
    assert response.status_code == 302
    assert response.url == "/"

    # Now logged in
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello userone!\n" in response.content

    # Check the user and connection that was created
    user = response.user
    assert user.username == "userone"
    assert user.email == "user@example.com"
    connections = user.oauth_connections.all()
    assert len(connections) == 1
    assert connections[0].provider_key == "github"
    assert connections[0].provider_user_id == "99"
    assert connections[0].access_token == "gho_key"
    assert connections[0].refresh_token == ""
    assert connections[0].access_token_expires_at is None
