from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from .exceptions import (
    OAuthCannotDisconnectError,
    OAuthStateMismatchError,
    OAuthUserAlreadyExistsError,
)
from .providers import get_oauth_provider_instance


class OAuthLoginView(View):
    def post(self, request, provider):
        if request.user.is_authenticated:
            return redirect("/")

        provider_instance = get_oauth_provider_instance(provider_key=provider)
        return provider_instance.handle_login_request(request=request)


class OAuthCallbackView(View):
    """
    The callback view is used for signup, login, and connect.
    """

    def get(self, request, provider):
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        try:
            return provider_instance.handle_callback_request(request=request)
        except OAuthUserAlreadyExistsError:
            return render(
                request,
                "oauthlogin/error.html",
                {
                    "oauth_error": "A user already exists with this email address. Please log in first and then connect this OAuth provider to the existing account."
                },
                status=400,
            )
        except OAuthStateMismatchError:
            return render(
                request,
                "oauthlogin/error.html",
                {"oauth_error": "The state parameter did not match. Please try again."},
                status=400,
            )


class OAuthConnectView(LoginRequiredMixin, View):
    def post(self, request, provider):
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        return provider_instance.handle_connect_request(request=request)


class OAuthDisconnectView(LoginRequiredMixin, View):
    def post(self, request, provider):
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        try:
            return provider_instance.handle_disconnect_request(request=request)
        except OAuthCannotDisconnectError:
            return render(
                request,
                "oauthlogin/error.html",
                {
                    "oauth_error": "This connection can't be removed. You must have a usable password or at least one active connection."
                },
                status=400,
            )
