from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import baggage

from plain.http import Response
from plain.http.cookie import unsign_cookie_value
from plain.runtime import settings

if TYPE_CHECKING:
    from plain.http import Request

__all__ = ["Observer", "ObserverMode", "PERSISTING_MODES", "RECORDING_MODES"]

logger = logging.getLogger(__name__)


class ObserverMode(Enum):
    """Observer operation modes."""

    SUMMARY = "summary"  # Real-time monitoring only, no DB export
    PERSIST = "persist"  # Real-time monitoring + DB export
    PERSIST_ONCE = "persist_once"  # Persist one trace then revert to summary
    DISABLED = "disabled"  # Observer explicitly disabled

    @classmethod
    def validate(cls, mode: str | None, source: str = "value") -> str | None:
        """Validate observer mode value.

        In DEBUG mode, raises ValueError for invalid values.
        In production, logs debug message and returns None for invalid values.

        Args:
            mode: The mode value to validate
            source: Description of where the mode came from (for error messages)

        Returns the mode if valid, None otherwise.
        """
        if mode is None:
            return None

        valid_modes = (
            cls.SUMMARY.value,
            cls.PERSIST.value,
            cls.PERSIST_ONCE.value,
            cls.DISABLED.value,
        )

        if mode not in valid_modes:
            if settings.DEBUG:
                raise ValueError(
                    f"Invalid Observer {source}: '{mode}'. "
                    f"Valid values are: {', '.join(valid_modes)}"
                )
            else:
                logger.debug(
                    "Invalid observer mode %s: '%s'. Expected one of: %s",
                    source,
                    mode,
                    valid_modes,
                )
                return None

        return mode


# Modes that trigger DB export and log capture
PERSISTING_MODES = (ObserverMode.PERSIST.value, ObserverMode.PERSIST_ONCE.value)
# All modes that record traces (summary + persisting)
RECORDING_MODES = (*PERSISTING_MODES, ObserverMode.SUMMARY.value)


class Observer:
    """Central class for managing observer state and operations."""

    COOKIE_NAME = "observer"
    DEBUG_HEADER_NAME = "Observer"
    SUMMARY_COOKIE_DURATION = 60 * 60 * 24 * 7  # 1 week in seconds
    PERSIST_COOKIE_DURATION = 60 * 60 * 24  # 1 day in seconds

    def __init__(
        self, *, cookies: Mapping[str, str], headers: Mapping[str, str]
    ) -> None:
        self.cookies = cookies
        self.headers = headers

    @classmethod
    def from_request(cls, request: Request) -> Observer:
        """Create an Observer instance from a request object."""
        return cls(cookies=request.cookies, headers=request.headers)

    @classmethod
    def from_otel_context(cls, context: Any) -> Observer:
        """Create an Observer instance from an OpenTelemetry context.

        This method extracts cookies and headers from the OTEL baggage.
        """
        cookies = cast(
            MutableMapping[str, str] | None,
            baggage.get_baggage("http.request.cookies", context),
        )
        if not cookies:
            cookies = {}

        headers = cast(
            MutableMapping[str, str] | None,
            baggage.get_baggage("http.request.headers", context),
        )
        if not headers:
            headers = {}

        return cls(cookies=dict(cookies), headers=dict(headers))

    def mode(self) -> str | None:
        """Get the current observer mode from header (DEBUG only) or cookie.

        In DEBUG mode, the Observer header takes precedence over the cookie.
        Returns 'summary', 'persist', 'disabled', or None.

        Raises ValueError if invalid value is found (DEBUG only).
        """
        # Check Observer header in DEBUG mode (takes precedence)
        if settings.DEBUG:
            if observer_header := self.headers.get(self.DEBUG_HEADER_NAME):
                observer_mode = observer_header.lower()
                return ObserverMode.validate(observer_mode, source="header value")

        # Check cookie
        observer_cookie = self.cookies.get(self.COOKIE_NAME)
        if not observer_cookie:
            return None

        try:
            mode = unsign_cookie_value(self.COOKIE_NAME, observer_cookie, default=None)
            return ObserverMode.validate(mode, source="cookie value")
        except Exception as e:
            logger.debug("Failed to unsign observer cookie: %s", e)
            return None

    def is_enabled(self) -> bool:
        """Check if observer is enabled (either summary or persist mode)."""
        return self.mode() in RECORDING_MODES

    def is_persisting(self) -> bool:
        """Check if full persisting (with DB export) is enabled."""
        return self.mode() in PERSISTING_MODES

    def is_recording_session(self) -> bool:
        """Check if in continuous recording mode (not persist-once)."""
        return self.mode() == ObserverMode.PERSIST.value

    def is_persist_once(self) -> bool:
        """Check if persist-once mode is enabled (single trace recording)."""
        return self.mode() == ObserverMode.PERSIST_ONCE.value

    def is_summarizing(self) -> bool:
        """Check if summary mode is enabled."""
        return self.mode() == ObserverMode.SUMMARY.value

    def is_disabled(self) -> bool:
        """Check if observer is explicitly disabled."""
        return self.mode() == ObserverMode.DISABLED.value

    def enable_summary_mode(self, response: Response) -> None:
        """Enable summary mode (real-time monitoring, no DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME,
            ObserverMode.SUMMARY.value,
            max_age=self.SUMMARY_COOKIE_DURATION,
        )

    def enable_persist_mode(self, response: Response) -> None:
        """Enable full persist mode (real-time monitoring + DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME,
            ObserverMode.PERSIST.value,
            max_age=self.PERSIST_COOKIE_DURATION,
        )

    def enable_persist_once_mode(self, response: Response) -> None:
        """Enable persist-once mode (persist one trace then revert to summary)."""
        response.set_signed_cookie(
            self.COOKIE_NAME,
            ObserverMode.PERSIST_ONCE.value,
            max_age=self.PERSIST_COOKIE_DURATION,
        )

    def disable(self, response: Response) -> None:
        """Disable observer by setting cookie to disabled."""
        response.set_signed_cookie(
            self.COOKIE_NAME,
            ObserverMode.DISABLED.value,
            max_age=self.PERSIST_COOKIE_DURATION,
        )

    def get_current_trace_stats(self) -> dict[str, Any] | None:
        """Get structured performance stats for the currently active trace."""
        from .otel import get_current_trace_stats

        return get_current_trace_stats()
