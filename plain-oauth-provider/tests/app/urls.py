from __future__ import annotations

from plain.oauth_provider import OAuthProviderRouter, OAuthWellKnownRouter
from plain.urls import Router, include, path
from plain.views import View


class StubLoginView(View):
    def get(self):
        return 200


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthProviderRouter),
        include(".well-known/", OAuthWellKnownRouter),
        path("login/", StubLoginView, name="login"),
    ]
