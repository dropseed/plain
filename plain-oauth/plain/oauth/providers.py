import datetime
import secrets
from typing import Any
from urllib.parse import urlencode

from plain.auth import login as auth_login
from plain.http import HttpRequest, Response, ResponseRedirect
from plain.runtime import settings
from plain.urls import reverse
from plain.utils.cache import add_never_cache_headers
from plain.utils.crypto import get_random_string
from plain.utils.module_loading import import_string

from .exceptions import OAuthError, OAuthStateMismatchError, OAuthStateMissingError
from .models import OAuthConnection

SESSION_STATE_KEY = "plainoauth_state"
SESSION_NEXT_KEY = "plainoauth_next"


class OAuthToken:
    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str = "",
        access_token_expires_at: datetime.datetime | None = None,
        refresh_token_expires_at: datetime.datetime | None = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.access_token_expires_at = access_token_expires_at
        self.refresh_token_expires_at = refresh_token_expires_at


class OAuthUser:
    def __init__(self, *, provider_id: str, user_model_fields: dict | None = None):
        self.provider_id = provider_id  # ID on the provider's system
        self.user_model_fields = user_model_fields or {}

    def __str__(self):
        if "email" in self.user_model_fields:
            return self.user_model_fields["email"]
        if "username" in self.user_model_fields:
            return self.user_model_fields["username"]
        return str(self.provider_id)


class OAuthProvider:
    authorization_url = ""

    def __init__(
        self,
        *,
        # Provided automatically
        provider_key: str,
        # Required as kwargs in OAUTH_LOGIN_PROVIDERS setting
        client_id: str,
        client_secret: str,
        # Not necessarily required, but commonly used
        scope: str = "",
    ):
        self.provider_key = provider_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope

    def get_authorization_url_params(self, *, request: HttpRequest) -> dict:
        return {
            "redirect_uri": self.get_callback_url(request=request),
            "client_id": self.get_client_id(),
            "scope": self.get_scope(),
            "state": self.generate_state(),
            "response_type": "code",
        }

    def refresh_oauth_token(self, *, oauth_token: OAuthToken) -> OAuthToken:
        raise NotImplementedError()

    def get_oauth_token(self, *, code: str, request: HttpRequest) -> OAuthToken:
        raise NotImplementedError()

    def get_oauth_user(self, *, oauth_token: OAuthToken) -> OAuthUser:
        raise NotImplementedError()

    def get_authorization_url(self, *, request: HttpRequest) -> str:
        return self.authorization_url

    def get_client_id(self) -> str:
        return self.client_id

    def get_client_secret(self) -> str:
        return self.client_secret

    def get_scope(self) -> str:
        return self.scope

    def get_callback_url(self, *, request: HttpRequest) -> str:
        url = reverse("oauth:callback", provider=self.provider_key)
        return request.build_absolute_uri(url)

    def generate_state(self) -> str:
        return get_random_string(length=32)

    def check_request_state(self, *, request: HttpRequest) -> None:
        if error := request.query_params.get("error"):
            raise OAuthError(error)

        try:
            state = request.query_params["state"]
        except KeyError as e:
            raise OAuthStateMissingError() from e

        expected_state = request.session.pop(SESSION_STATE_KEY)
        request.session.save()  # Make sure the pop is saved (won't save on an exception)
        if not secrets.compare_digest(state, expected_state):
            raise OAuthStateMismatchError()

    def handle_login_request(
        self, *, request: HttpRequest, redirect_to: str = ""
    ) -> Response:
        authorization_url = self.get_authorization_url(request=request)
        authorization_params = self.get_authorization_url_params(request=request)

        if "state" in authorization_params:
            # Store the state in the session so we can check on callback
            request.session[SESSION_STATE_KEY] = authorization_params["state"]

        # Store next url in session so we can get it on the callback request
        if redirect_to:
            request.session[SESSION_NEXT_KEY] = redirect_to
        elif "next" in request.data:
            request.session[SESSION_NEXT_KEY] = request.data["next"]

        # Sort authorization params for consistency
        sorted_authorization_params = sorted(authorization_params.items())
        redirect_url = authorization_url + "?" + urlencode(sorted_authorization_params)
        return self.get_redirect_response(redirect_url)

    def handle_connect_request(
        self, *, request: HttpRequest, redirect_to: str = ""
    ) -> Response:
        return self.handle_login_request(request=request, redirect_to=redirect_to)

    def handle_disconnect_request(self, *, request: HttpRequest) -> Response:
        provider_user_id = request.data["provider_user_id"]
        connection = OAuthConnection.objects.get(
            provider_key=self.provider_key, provider_user_id=provider_user_id
        )
        connection.delete()
        redirect_url = self.get_disconnect_redirect_url(request=request)
        return self.get_redirect_response(redirect_url)

    def handle_callback_request(self, *, request: HttpRequest) -> Response:
        self.check_request_state(request=request)

        oauth_token = self.get_oauth_token(
            code=request.query_params["code"], request=request
        )
        oauth_user = self.get_oauth_user(oauth_token=oauth_token)

        if request.user:
            connection = OAuthConnection.connect(
                user=request.user,
                provider_key=self.provider_key,
                oauth_token=oauth_token,
                oauth_user=oauth_user,
            )
            user = connection.user
        else:
            connection = OAuthConnection.get_or_create_user(
                provider_key=self.provider_key,
                oauth_token=oauth_token,
                oauth_user=oauth_user,
            )

            user = connection.user

            self.login(request=request, user=user)

        redirect_url = self.get_login_redirect_url(request=request)
        return self.get_redirect_response(redirect_url)

    def login(self, *, request: HttpRequest, user: Any) -> None:
        auth_login(request=request, user=user)

    def get_login_redirect_url(self, *, request: HttpRequest) -> str:
        return request.session.pop(SESSION_NEXT_KEY, "/")

    def get_disconnect_redirect_url(self, *, request: HttpRequest) -> str:
        return request.data.get("next", "/")

    def get_redirect_response(self, redirect_url: str) -> Response:
        """
        Returns a redirect response to the given URL.
        This is a utility method to ensure consistent redirect handling.
        """
        response = ResponseRedirect(redirect_url)
        add_never_cache_headers(response)
        return response


def get_oauth_provider_instance(*, provider_key: str) -> OAuthProvider:
    OAUTH_LOGIN_PROVIDERS = getattr(settings, "OAUTH_LOGIN_PROVIDERS", {})
    provider_class_path = OAUTH_LOGIN_PROVIDERS[provider_key]["class"]
    provider_class = import_string(provider_class_path)
    provider_kwargs = OAUTH_LOGIN_PROVIDERS[provider_key].get("kwargs", {})
    return provider_class(provider_key=provider_key, **provider_kwargs)


def get_provider_keys() -> list[str]:
    return list(getattr(settings, "OAUTH_LOGIN_PROVIDERS", {}).keys())
