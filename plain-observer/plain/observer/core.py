"""
Core observability functionality and Observer class.
"""

from .processor import get_span_processor


class Observer:
    """Central class for managing observability state and operations."""

    COOKIE_NAME = "observer"
    COOKIE_DURATION = 60 * 60 * 24  # 1 day in seconds

    def __init__(self, request):
        self.request = request

    @property
    def mode(self):
        """Get the current observability mode from signed cookie."""
        return self.request.get_signed_cookie(self.COOKIE_NAME, default=None)

    @property
    def is_enabled(self):
        """Check if observability is enabled (either record or sample mode)."""
        return self.mode in ("record", "sample")

    @property
    def is_sampling(self):
        """Check if full sampling (with DB export) is enabled."""
        return self.mode == "sample"

    @property
    def is_recording(self):
        """Check if record-only mode is enabled."""
        return self.mode == "record"

    def enable_record_mode(self, response):
        """Enable record-only mode (real-time monitoring, no DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME, "record", max_age=self.COOKIE_DURATION
        )

    def enable_sample_mode(self, response):
        """Enable full sampling mode (real-time monitoring + DB export)."""
        response.set_signed_cookie(
            self.COOKIE_NAME, "sample", max_age=self.COOKIE_DURATION
        )

    def disable(self, response):
        """Disable observability by deleting the cookie."""
        response.delete_cookie(self.COOKIE_NAME)

    def get_current_trace_summary(self):
        """Get performance summary string for the currently active trace."""

        span_collector = get_span_processor()
        if not span_collector:
            return None

        return span_collector.get_current_trace_summary()
