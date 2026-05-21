from __future__ import annotations

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings


@register_check(name="connect.secret_key")
class CheckConnectSecretKey(PreflightCheck):
    def run(self) -> list[PreflightResult]:
        if str(settings.CONNECT_SECRET_KEY):
            return []
        if not settings.CONNECT_PAGEVIEWS_TOKEN:
            return []
        return [
            PreflightResult(
                fix=(
                    "CONNECT_PAGEVIEWS_TOKEN is set but CONNECT_SECRET_KEY is empty. "
                    "Get the shared secret from the App settings page on Plain Cloud "
                    "and set CONNECT_SECRET_KEY in app/settings.py (or the "
                    "PLAIN_CONNECT_SECRET_KEY env var), or unset the token."
                ),
                id="connect.secret_key_missing",
                warning=True,
            )
        ]
