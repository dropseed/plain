import datetime

import requests

from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser
from plain.utils import timezone


class BitbucketOAuthProvider(OAuthProvider):
    authorization_url = "https://bitbucket.org/site/oauth2/authorize"

    def _get_token(self, request_data):
        response = requests.post(
            "https://bitbucket.org/site/oauth2/access_token",
            auth=(self.get_client_id(), self.get_client_secret()),
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
            access_token_expires_at=timezone.now()
            + datetime.timedelta(seconds=data["expires_in"]),
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
            "https://api.bitbucket.org/2.0/user",
            headers={
                "Authorization": f"Bearer {oauth_token.access_token}",
            },
        )
        response.raise_for_status()
        user_id = response.json()["uuid"]
        username = response.json()["username"]

        response = requests.get(
            "https://api.bitbucket.org/2.0/user/emails",
            headers={
                "Authorization": f"Bearer {oauth_token.access_token}",
            },
        )
        response.raise_for_status()
        confirmed_primary_email = [
            x["email"]
            for x in response.json()["values"]
            if x["is_primary"] and x["is_confirmed"]
        ][0]

        return OAuthUser(
            id=user_id,
            email=confirmed_primary_email,
            username=username,
        )
