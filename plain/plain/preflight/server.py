from __future__ import annotations

from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult


@register_check(name="server.keepalive_timeout")
class CheckServerKeepaliveTimeout(PreflightCheck):
    """SERVER_KEEPALIVE_TIMEOUT must be positive.

    A non-positive value makes the server close connections whose
    responses promised keep-alive, dropping the next request written
    onto them (see SERVER_KEEPALIVE_TIMEOUT in global_settings.py).
    """

    def run(self) -> list[PreflightResult]:
        if settings.SERVER_KEEPALIVE_TIMEOUT > 0:
            return []
        return [
            PreflightResult(
                fix=f"SERVER_KEEPALIVE_TIMEOUT must be positive "
                f"(got {settings.SERVER_KEEPALIVE_TIMEOUT}).",
                id="server.keepalive_timeout_invalid",
            )
        ]
