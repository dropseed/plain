from __future__ import annotations

__all__ = [
    "OAuthProviderRouter",
    "OAuthWellKnownRouter",
]


def __getattr__(name: str):
    if name in ("OAuthProviderRouter", "OAuthWellKnownRouter"):
        from .urls import OAuthProviderRouter, OAuthWellKnownRouter

        return {
            "OAuthProviderRouter": OAuthProviderRouter,
            "OAuthWellKnownRouter": OAuthWellKnownRouter,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
