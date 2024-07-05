import requests

from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser


class GitLabOAuthProvider(OAuthProvider):
    authorization_url = "https://gitlab.com/oauth/authorize"

    def _get_token(self, request_data):
        request_data["client_id"] = self.get_client_id()
        request_data["client_secret"] = self.get_client_secret()
        response = requests.post(
            "https://gitlab.com/oauth/token",
            headers={
                "Accept": "application/json",
            },
            data=request_data,
        )
        response.raise_for_status()
        data = response.json()
        return OAuthToken(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            # expires_in is missing in response?
        )

    def get_oauth_token(self, *, code, request):
        return self._get_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.get_callback_url(request=request),
            }
        )

    def refresh_oauth_token(self, *, oauth_token):
        return self._get_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": oauth_token.refresh_token,
            }
        )

    def get_oauth_user(self, *, oauth_token):
        response = requests.get(
            "https://gitlab.com/api/v4/user",
            headers={
                "Authorization": f"Bearer {oauth_token.access_token}",
            },
        )
        response.raise_for_status()
        data = response.json()
        return OAuthUser(
            id=data["id"],
            email=data["email"],
            username=data["username"],
        )
