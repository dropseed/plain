import datetime
import secrets
from typing import List
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.module_loading import import_string

from .exceptions import OAuthCannotDisconnectError, OAuthStateMismatchError
from .models import OAuthConnection

SESSION_STATE_KEY = "oauth_login_state"
SESSION_NEXT_KEY = "oauth_login_next"


class OAuthToken:
    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str = "",
        access_token_expires_at: datetime.datetime = None,
        refresh_token_expires_at: datetime.datetime = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.access_token_expires_at = access_token_expires_at
        self.refresh_token_expires_at = refresh_token_expires_at


class OAuthUser:
    def __init__(self, *, id: str, email: str, username: str = ""):
        self.id = id
        self.username = username
        self.email = email


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
        url = reverse("oauth_login:callback", kwargs={"provider": self.provider_key})
        return request.build_absolute_uri(url)

    def generate_state(self) -> str:
        return get_random_string(length=32)

    def check_request_state(self, *, request: HttpRequest) -> None:
        state = request.GET["state"]
        expected_state = request.session.pop(SESSION_STATE_KEY)
        if not secrets.compare_digest(state, expected_state):
            raise OAuthStateMismatchError()

    def handle_login_request(self, *, request: HttpRequest) -> HttpResponse:
        authorization_url = self.get_authorization_url(request=request)
        authorization_params = self.get_authorization_url_params(request=request)

        if "state" in authorization_params:
            # Store the state in the session so we can check on callback
            request.session[SESSION_STATE_KEY] = authorization_params["state"]

        if "next" in request.POST:
            # Store in session so we can get it on the callback request
            request.session[SESSION_NEXT_KEY] = request.POST["next"]

        # Sort authorization params for consistency
        sorted_authorization_params = sorted(authorization_params.items())
        redirect_url = authorization_url + "?" + urlencode(sorted_authorization_params)
        return HttpResponseRedirect(redirect_url)

    def handle_connect_request(self, *, request: HttpRequest) -> HttpResponse:
        return self.handle_login_request(request=request)

    def handle_disconnect_request(self, *, request: HttpRequest) -> HttpResponse:
        provider_user_id = request.POST["provider_user_id"]
        connection = OAuthConnection.objects.get(
            provider_key=self.provider_key, provider_user_id=provider_user_id
        )
        if (
            request.user.has_usable_password()
            or request.user.oauth_connections.count() > 1
        ):
            connection.delete()
        else:
            raise OAuthCannotDisconnectError(
                "Cannot remove last OAuth connection without a usable password"
            )

        redirect_url = self.get_disconnect_redirect_url(request=request)
        return HttpResponseRedirect(redirect_url)

    def handle_callback_request(self, *, request: HttpRequest) -> HttpResponse:
        self.check_request_state(request=request)

        oauth_token = self.get_oauth_token(code=request.GET["code"], request=request)
        oauth_user = self.get_oauth_user(oauth_token=oauth_token)

        if request.user.is_authenticated:
            connection = OAuthConnection.connect(
                user=request.user,
                provider_key=self.provider_key,
                oauth_token=oauth_token,
                oauth_user=oauth_user,
            )
            user = connection.user
        else:
            connection = OAuthConnection.get_or_createuser(
                provider_key=self.provider_key,
                oauth_token=oauth_token,
                oauth_user=oauth_user,
            )

            user = connection.user

            # Log them in
            login(request, user)

        redirect_url = self.get_login_redirect_url(request=request)
        return HttpResponseRedirect(redirect_url)

    def get_login_redirect_url(self, *, request: HttpRequest) -> str:
        return request.session.pop(SESSION_NEXT_KEY, settings.LOGIN_REDIRECT_URL)

    def get_disconnect_redirect_url(self, *, request: HttpRequest) -> str:
        return request.POST.get("next", "/")


def get_oauth_provider_instance(*, provider_key: str) -> OAuthProvider:
    OAUTH_LOGIN_PROVIDERS = getattr(settings, "OAUTH_LOGIN_PROVIDERS", {})
    provider_class_path = OAUTH_LOGIN_PROVIDERS[provider_key]["class"]
    provider_class = import_string(provider_class_path)
    provider_kwargs = OAUTH_LOGIN_PROVIDERS[provider_key].get("kwargs", {})
    return provider_class(provider_key=provider_key, **provider_kwargs)


def get_provider_keys() -> List[str]:
    return list(getattr(settings, "OAUTH_LOGIN_PROVIDERS", {}).keys())
