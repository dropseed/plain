from __future__ import annotations

from plain.urls import Router, path

from .views import (
    AuthorizationServerMetadataView,
    AuthorizeView,
    RegisterView,
    RevocationView,
    TokenView,
)


class OAuthServerRouter(Router):
    namespace = "oauthserver"
    urls = [
        path("authorize", AuthorizeView, name="authorize"),
        path("token", TokenView, name="token"),
        path("register", RegisterView, name="register"),
        path("revoke", RevocationView, name="revoke"),
    ]


class OAuthWellKnownRouter(Router):
    """Mount at .well-known/ in your root router."""

    namespace = ""
    urls = [
        path(
            "oauth-authorization-server",
            AuthorizationServerMetadataView,
            name="oauth_authorization_server_metadata",
            # RFC 8414 fixes this path exactly — clients construct it themselves
            # and may not follow redirects, so it must serve 200 even when the
            # app canonicalizes URLs with URLS_TRAILING_SLASH=True.
            force_trailing_slash=False,
        ),
    ]
