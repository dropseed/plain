import datetime

import requests

from plain.oauth.exceptions import OAuthError
from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser
from plain.utils import timezone


class GitHubOAuthProvider(OAuthProvider):
    authorization_url = "https://github.com/login/oauth/authorize"

    github_token_url = "https://github.com/login/oauth/access_token"
    github_user_url = "https://api.github.com/user"
    github_emails_url = "https://api.github.com/user/emails"

    def _get_token(self, request_data):
        response = requests.post(
            self.github_token_url,
            headers={
                "Accept": "application/json",
            },
            data=request_data,
        )
        response.raise_for_status()
        data = response.json()

        oauth_token = OAuthToken(
            access_token=data["access_token"],
        )

        # Expiration and refresh tokens are optional in GitHub depending on the app
        if "expires_in" in data:
            oauth_token.access_token_expires_at = timezone.now() + datetime.timedelta(
                seconds=data["expires_in"]
            )

        if "refresh_token" in data:
            oauth_token.refresh_token = data["refresh_token"]

        if "refresh_token_expires_in" in data:
            oauth_token.refresh_token_expires_at = timezone.now() + datetime.timedelta(
                seconds=data["refresh_token_expires_in"]
            )

        return oauth_token

    def get_oauth_token(self, *, code, request):
        return self._get_token(
            {
                "client_id": self.get_client_id(),
                "client_secret": self.get_client_secret(),
                "code": code,
            }
        )

    def refresh_oauth_token(self, *, oauth_token):
        return self._get_token(
            {
                "client_id": self.get_client_id(),
                "client_secret": self.get_client_secret(),
                "refresh_token": oauth_token.refresh_token,
                "grant_type": "refresh_token",
            }
        )

    def get_oauth_user(self, *, oauth_token):
        response = requests.get(
            self.github_user_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"token {oauth_token.access_token}",
            },
        )
        response.raise_for_status()
        data = response.json()
        user_id = data["id"]
        username = data["login"]

        # Use the verified, primary email address (not the public profile email, which is optional anyway)
        response = requests.get(
            self.github_emails_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"token {oauth_token.access_token}",
            },
        )
        response.raise_for_status()

        try:
            verified_primary_email = [
                x["email"] for x in response.json() if x["primary"] and x["verified"]
            ][0]
        except IndexError:
            raise OAuthError("A verified primary email address is required on GitHub")

        return OAuthUser(
            provider_id=user_id,
            user_model_fields={
                "email": verified_primary_email,
                "username": username,
            },
        )
