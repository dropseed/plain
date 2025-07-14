"""
Core observability functionality and Observer class.
"""


class Observer:
    """Central class for managing observability state and operations."""

    def __init__(self, request):
        self.request = request

    @property
    def mode(self):
        """Get the current observability mode from signed cookie."""
        return self.request.get_signed_cookie("observe", default=None)

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
        response.set_signed_cookie("observe", "record", max_age=60 * 60 * 24)

    def enable_sample_mode(self, response):
        """Enable full sampling mode (real-time monitoring + DB export)."""
        response.set_signed_cookie("observe", "sample", max_age=60 * 60 * 24)

    def disable(self, response):
        """Disable observability by deleting the cookie."""
        response.delete_cookie("observe")

    def get_current_trace_summary(self):
        """Get performance summary string for the currently active trace."""
        from .otel import get_span_collector

        span_collector = get_span_collector()
        if not span_collector:
            return None

        return span_collector.get_current_trace_summary()
