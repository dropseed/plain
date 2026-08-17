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


@register_check(name="server.body_limits")
class CheckServerBodyLimits(PreflightCheck):
    """The server body-size settings must compose into workable limits.

    The memory threshold is clamped to the policy cap at runtime — a
    body small enough to stay in memory must also be small enough to
    accept — so a threshold above the cap silently has no effect. And an
    in-flight budget below the cap means no maximum-size request can
    ever be accepted: it would trip the worker-wide 503 even on an
    otherwise idle server.
    """

    def run(self) -> list[PreflightResult]:
        cap = settings.SERVER_MAX_REQUEST_BODY_SIZE
        memory_size = settings.SERVER_BODY_MAX_MEMORY_SIZE
        inflight = settings.SERVER_MAX_INFLIGHT_BODY_SIZE
        if cap is not None and cap < 0:
            return [
                PreflightResult(
                    fix=f"SERVER_MAX_REQUEST_BODY_SIZE must be non-negative or "
                    f"None (got {cap}).",
                    id="server.max_request_body_invalid",
                )
            ]
        if memory_size <= 0:
            return [
                PreflightResult(
                    fix=f"SERVER_BODY_MAX_MEMORY_SIZE must be positive "
                    f"(got {memory_size}).",
                    id="server.body_max_memory_invalid",
                )
            ]
        min_rate = settings.SERVER_BODY_MIN_BYTES_PER_SECOND
        if min_rate < 0:
            return [
                PreflightResult(
                    fix=f"SERVER_BODY_MIN_BYTES_PER_SECOND must be non-negative "
                    f"(got {min_rate}).",
                    id="server.body_min_rate_invalid",
                )
            ]
        if inflight is not None and inflight < 0:
            return [
                PreflightResult(
                    fix=f"SERVER_MAX_INFLIGHT_BODY_SIZE must be non-negative or "
                    f"None (got {inflight}).",
                    id="server.max_inflight_body_invalid",
                )
            ]
        results = []
        if cap is not None and memory_size > cap:
            results.append(
                PreflightResult(
                    fix=f"SERVER_BODY_MAX_MEMORY_SIZE ({memory_size}) is larger than "
                    f"SERVER_MAX_REQUEST_BODY_SIZE ({cap}) and will be clamped to "
                    f"it — raise the cap or lower the memory threshold.",
                    id="server.body_max_memory_exceeds_cap",
                    warning=True,
                )
            )
        if inflight is not None and cap is not None and inflight < cap:
            results.append(
                PreflightResult(
                    fix=f"SERVER_MAX_INFLIGHT_BODY_SIZE ({inflight}) is smaller "
                    f"than SERVER_MAX_REQUEST_BODY_SIZE ({cap}), so a "
                    f"maximum-size request body can never be accepted — raise "
                    f"the in-flight budget or lower the cap.",
                    id="server.max_inflight_body_below_cap",
                    warning=True,
                )
            )
        return results
