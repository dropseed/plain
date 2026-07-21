from __future__ import annotations

from plain.oauthserver.urls import OAuthServerRouter, OAuthWellKnownRouter
from plain.urls import Router, include, path
from plain.views import View


class StubLoginView(View):
    def get(self):
        return 200


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthServerRouter),
        include(".well-known/", OAuthWellKnownRouter),
        path("login/", StubLoginView, name="login"),
    ]
