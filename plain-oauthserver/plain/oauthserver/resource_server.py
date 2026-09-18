"""Resource-server side: validate access tokens issued by this server.

Kept separate from the authorization-server views so a resource server (e.g. a
`plain.mcp` endpoint) can validate tokens without importing the view layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AccessToken


def validate_access_token(
    token: str, *, resource: str | None = None
) -> AccessToken | None:
    """Return the live `AccessToken` for a bearer value, or `None`.

    `None` covers unknown, expired, and revoked tokens. When `resource` is
    given and the token is audience-bound (RFC 8707), the bound resource must
    match — a token minted for a different endpoint is rejected. Omitting
    `resource` (or a token with no bound resource) skips the audience check, so
    pass `resource=` whenever the caller is a specific endpoint.
    """
    from .models import AccessToken, _hash_token

    try:
        access_token = AccessToken.query.select_related("user").get(
            token_hash=_hash_token(token)
        )
    except AccessToken.DoesNotExist:
        return None

    if not access_token.is_valid():
        return None
    if resource and access_token.resource and access_token.resource != resource:
        return None
    return access_token
