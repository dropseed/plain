from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .urls import OAuthProviderRouter as OAuthProviderRouter
    from .urls import OAuthWellKnownRouter as OAuthWellKnownRouter

__all__ = [
    "OAuthProviderRouter",
    "OAuthWellKnownRouter",
]


def __getattr__(name: str) -> type:
    if name in ("OAuthProviderRouter", "OAuthWellKnownRouter"):
        from .urls import OAuthProviderRouter, OAuthWellKnownRouter

        return {
            "OAuthProviderRouter": OAuthProviderRouter,
            "OAuthWellKnownRouter": OAuthWellKnownRouter,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
