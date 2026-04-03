from __future__ import annotations

from plain.urls import Router, path

from .views import (
    AuthorizationServerMetadataView,
    AuthorizeView,
    RevocationView,
    TokenView,
)


class OAuthProviderRouter(Router):
    namespace = "oauth_provider"
    urls = [
        path("authorize/", AuthorizeView, name="authorize"),
        path("token/", TokenView, name="token"),
        path("revoke/", RevocationView, name="revoke"),
    ]


class OAuthWellKnownRouter(Router):
    """Mount at .well-known/ in your root router."""

    namespace = ""
    urls = [
        path(
            "oauth-authorization-server",
            AuthorizationServerMetadataView,
            name="oauth_authorization_server_metadata",
        ),
    ]
