"""OAuth 2.1 resource-server support for MCP endpoints (RFC 9728).

`plain.mcp` stays agnostic about who issues tokens — implement
`authenticate_token` to validate the bearer against your authorization server
(for example `plain.oauthserver.validate_access_token`). This is the
server side of the flow an MCP client like Claude's custom connector runs:
an unauthenticated request gets a 401 whose `WWW-Authenticate` header points
at the protected-resource metadata, which names the authorization server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

from plain.http import JsonResponse, Request, Response
from plain.views import View

from .exceptions import MCPUnauthorized

_WELL_KNOWN_PRM = "/.well-known/oauth-protected-resource"


def _canonical_resource(url: str) -> str:
    """Canonical audience identifier: lowercase scheme + host, no trailing slash.

    Keeps the advertised `resource` and the validated audience byte-identical
    regardless of trailing-slash config or client-side normalization (RFC 8707).
    """
    parsed = urlparse(url)
    return urlunparse(
        parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=parsed.path.rstrip("/"),
        )
    )


@dataclass
class TokenInfo:
    """Who a validated bearer token belongs to, and what it may do."""

    user: Any
    scopes: frozenset[str] = field(default_factory=frozenset)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    # RFC 7235: the auth-scheme is matched case-insensitively.
    return value.strip() if scheme.lower() == "bearer" else ""


class OAuthResourceServer:
    """Mixin for an `MCPView` that authenticates requests with OAuth bearer tokens.

    Subclass alongside `MCPView` and implement `authenticate_token`:

        class AppMCP(OAuthResourceServer, MCPView):
            name = "myapp"
            tools = [...]

            def authenticate_token(self, token):
                at = validate_access_token(token, resource=self.oauth_resource)
                return TokenInfo(at.user, at.scopes) if at else None

    Name the authorization server on the companion `MCPProtectedResourceView`,
    not here. On success `self.user` and `self.scopes` are set for tools to read
    via `self.mcp`. On failure the request gets a 401 with an RFC 9728
    `WWW-Authenticate` challenge pointing at the protected-resource metadata.
    """

    user: Any = None
    scopes: frozenset[str] = frozenset()

    # Provided by the MCPView this mixin is combined with.
    request: Request

    def authenticate_token(self, token: str) -> TokenInfo | None:
        raise NotImplementedError

    def before_request(self) -> None:
        token = _bearer_token(self.request)
        info = self.authenticate_token(token) if token else None
        if info is None:
            # RFC 6750: a token that was supplied but rejected is invalid_token;
            # a missing token just gets the bare discovery challenge.
            error = "invalid_token" if token else None
            raise MCPUnauthorized(
                "Authentication required", www_authenticate=self._challenge(error)
            )
        self.user = info.user
        self.scopes = info.scopes

    @property
    def oauth_resource(self) -> str:
        """The canonical URI of this MCP endpoint — the token audience."""
        return _canonical_resource(self.request.build_absolute_uri(self.request.path))

    def _challenge(self, error: str | None = None) -> str:
        metadata_url = self.request.build_absolute_uri(
            _WELL_KNOWN_PRM + self.request.path
        )
        challenge = f'Bearer resource_metadata="{metadata_url}"'
        if error:
            challenge += f', error="{error}"'
        return challenge


class MCPProtectedResourceView(View):
    """Serves RFC 9728 protected-resource metadata for an MCP endpoint.

    Mount at `.well-known/oauth-protected-resource/<mcp-path>` (the path the
    `OAuthResourceServer` challenge points to). `authorization_servers` defaults
    to this app's own origin — set it only when an external IdP issues the
    tokens. The `resource` is derived from the request path, so one view can sit
    in front of any MCP mount point.
    """

    authorization_servers: list[str] = []
    oauth_scopes_supported: list[str] = []

    def get(self) -> Response:
        resource_path = self.request.path.removeprefix(_WELL_KNOWN_PRM) or "/"
        # Same app issues the tokens by default; override for an external IdP.
        origin = f"{self.request.scheme}://{self.request.host}"
        servers = self.authorization_servers or [origin]
        metadata: dict[str, Any] = {
            "resource": _canonical_resource(
                self.request.build_absolute_uri(resource_path)
            ),
            "authorization_servers": list(servers),
            "bearer_methods_supported": ["header"],
        }
        if self.oauth_scopes_supported:
            metadata["scopes_supported"] = list(self.oauth_scopes_supported)
        return JsonResponse(metadata)
