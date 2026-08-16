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


@register_check(name="server.body_prebuffer_size")
class CheckServerBodyPrebufferSize(PreflightCheck):
    """SERVER_BODY_PREBUFFER_SIZE above SERVER_MAX_REQUEST_BODY_SIZE is inert.

    The pre-buffer threshold is clamped to the policy cap at runtime — a
    body small enough to pre-buffer must also be small enough to accept —
    so a prebuffer setting above the cap silently has no effect.
    """

    def run(self) -> list[PreflightResult]:
        cap = settings.SERVER_MAX_REQUEST_BODY_SIZE
        prebuffer = settings.SERVER_BODY_PREBUFFER_SIZE
        if cap is not None and cap < 0:
            return [
                PreflightResult(
                    fix=f"SERVER_MAX_REQUEST_BODY_SIZE must be non-negative or "
                    f"None (got {cap}).",
                    id="server.max_request_body_invalid",
                )
            ]
        if prebuffer <= 0:
            return [
                PreflightResult(
                    fix=f"SERVER_BODY_PREBUFFER_SIZE must be positive "
                    f"(got {prebuffer}).",
                    id="server.body_prebuffer_invalid",
                )
            ]
        if cap is None or prebuffer <= cap:
            return []
        return [
            PreflightResult(
                fix=f"SERVER_BODY_PREBUFFER_SIZE ({prebuffer}) is larger than "
                f"SERVER_MAX_REQUEST_BODY_SIZE ({cap}) and will be clamped to "
                f"it — raise the cap or lower the prebuffer size.",
                id="server.body_prebuffer_exceeds_cap",
                warning=True,
            )
        ]
