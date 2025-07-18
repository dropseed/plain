from enum import Enum


class ObserverMode(Enum):
    """Observer operation modes."""

    SUMMARY = "summary"  # Real-time monitoring only, no DB export
    PERSIST = "persist"  # Real-time monitoring + DB export
    DISABLED = "disabled"  # Observer explicitly disabled


class Observer:
    """Central class for managing observer state and operations."""

    COOKIE_NAME = "observer"
    COOKIE_DURATION = 60 * 60 * 24  # 1 day in seconds

    def __init__(self, request):
        self.request = request

    def mode(self):
        """Get the current observer mode from signed cookie."""
        return self.request.get_signed_cookie(self.COOKIE_NAME, default=None)

    def is_enabled(self):
        """Check if observer is enabled (either summary or persist mode)."""
        return self.mode() in (ObserverMode.SUMMARY.value, ObserverMode.PERSIST.value)

    def is_persisting(self):
        """Check if full persisting (with DB export) is enabled."""
        return self.mode() == ObserverMode.PERSIST.value

    def is_summarizing(self):
        """Check if summary mode is enabled."""
        return self.mode() == ObserverMode.SUMMARY.value

    def is_disabled(self):
        """Check if observer is explicitly disabled."""
        return self.mode() == ObserverMode.DISABLED.value

    def enable_summary_mode(self, response):
        """Enable summary mode (real-time monitoring, no DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME, ObserverMode.SUMMARY.value, max_age=self.COOKIE_DURATION
        )

    def enable_persist_mode(self, response):
        """Enable full persist mode (real-time monitoring + DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME, ObserverMode.PERSIST.value, max_age=self.COOKIE_DURATION
        )

    def disable(self, response):
        """Disable observer by setting cookie to disabled."""
        response.set_signed_cookie(
            self.COOKIE_NAME, ObserverMode.DISABLED.value, max_age=self.COOKIE_DURATION
        )

    def get_current_trace_summary(self):
        """Get performance summary string for the currently active trace."""
        from .otel import get_current_trace_summary

        return get_current_trace_summary()
