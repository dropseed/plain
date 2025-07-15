import logging
import threading
import time
from collections import defaultdict

import opentelemetry.context as context_api
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import SpanProcessor

from plain.http.cookie import unsign_cookie_value

from .exporter import ObserverExporter

logger = logging.getLogger(__name__)


def get_span_processor():
    """Get the span collector instance from the tracer provider."""
    if not (current_provider := trace.get_tracer_provider()):
        return None

    # Look for ObserverSpanProcessor in the span processors
    # Check if the provider has a _active_span_processor attribute
    if hasattr(current_provider, "_active_span_processor"):
        # It's a composite processor, check its _span_processors
        if composite_processor := current_provider._active_span_processor:
            if hasattr(composite_processor, "_span_processors"):
                for processor in composite_processor._span_processors:
                    if isinstance(processor, ObserverSpanProcessor):
                        return processor

    return None


def get_current_trace_summary() -> str | None:
    """Get performance summary for the currently active trace."""
    if not (current_span := trace.get_current_span()):
        return None

    if not (processor := get_span_processor()):
        return None

    trace_id = format(current_span.get_span_context().trace_id, "032x")
    return processor.get_trace_summary(trace_id)


class ObserverSpanProcessor(SpanProcessor):
    """Collects spans in real-time for current trace performance monitoring.

    This processor keeps spans in memory for traces that have the 'view' or 'sample'
    cookie set. These spans can be accessed via get_current_trace_summary() for
    real-time debugging. Spans with 'sample' cookie will also be persisted to the
    database via the ObserverExporter.
    """

    def __init__(self):
        # Span storage
        self._traces = defaultdict(
            lambda: {
                "active": {},  # span_id -> span
                "completed": [],  # list of spans
                "root_span_id": None,
                "mode": None,
                "should_keep": False,
            }
        )
        self._traces_lock = threading.Lock()
        self._exporter = ObserverExporter()

    def on_start(self, span, parent_context=None):
        """Called when a span starts."""
        trace_id = format(span.get_span_context().trace_id, "032x")
        span_id = format(span.get_span_context().span_id, "016x")

        with self._traces_lock:
            trace_info = self._traces[trace_id]

            # First span in trace - determine if we should keep it
            if not trace_info["mode"]:
                should_keep, mode = self._get_recording_decision(parent_context)
                trace_info["should_keep"] = should_keep
                trace_info["mode"] = mode

                # Clean up old traces if too many
                if len(self._traces) > 1000:
                    # Remove oldest 100 traces
                    oldest_ids = sorted(self._traces.keys())[:100]
                    for old_id in oldest_ids:
                        del self._traces[old_id]

            # Store span if we're keeping this trace
            if trace_info["should_keep"]:
                trace_info["active"][span_id] = span

                # Track root span
                if not span.parent:
                    trace_info["root_span_id"] = span_id

    def on_end(self, span):
        """Called when a span ends."""
        trace_id = format(span.get_span_context().trace_id, "032x")
        span_id = format(span.get_span_context().span_id, "016x")

        with self._traces_lock:
            trace_info = self._traces.get(trace_id)
            if not trace_info or not trace_info["should_keep"]:
                return

            # Move span from active to completed
            if span_obj := trace_info["active"].pop(span_id, None):
                trace_info["completed"].append(span_obj)

            # Check if trace is complete (root span ended)
            if span_id == trace_info["root_span_id"]:
                # Export if in sample mode
                if trace_info["mode"] == "sample" and trace_info["completed"]:
                    logger.info(
                        "Exporting %d spans for trace %s",
                        len(trace_info["completed"]),
                        trace_id,
                    )
                    self._exporter.export(trace_info["completed"])

                # Clean up trace
                del self._traces[trace_id]

    def get_trace_summary(self, trace_id: str) -> str | None:
        """Get performance summary for a specific trace."""
        with self._traces_lock:
            if (
                not (trace_info := self._traces.get(trace_id))
                or not trace_info["should_keep"]
            ):
                return None

            # Combine active and completed spans
            if not (
                all_spans := list(trace_info["active"].values())
                + trace_info["completed"]
            ):
                return None

            # Calculate stats
            total_spans = len(all_spans)
            db_queries = sum(
                1 for s in all_spans if s.attributes and s.attributes.get("db.system")
            )

            # Calculate duration
            start_times = [s.start_time for s in all_spans if s.start_time]
            end_times = [s.end_time for s in all_spans if s.end_time]

            duration_ms = 0.0
            if start_times:
                earliest_start = min(start_times)
                if end_times:
                    latest_end = max(end_times)
                    duration_ms = (latest_end - earliest_start) / 1_000_000
                else:
                    # Trace still active
                    current_time_ns = int(time.time() * 1_000_000_000)
                    duration_ms = (current_time_ns - earliest_start) / 1_000_000

            # Build summary
            parts = [f"{total_spans}sp"]
            if db_queries:
                parts.append(f"{db_queries}db")
            if duration_ms:
                parts.append(f"{round(duration_ms, 1)}ms")

            return " ".join(parts)

    def _get_recording_decision(self, parent_context=None) -> tuple[bool, str | None]:
        """Determine if we should record this trace based on cookies."""
        if not (context := parent_context or context_api.get_current()):
            return False, None

        if not (cookies := baggage.get_baggage("http.request.cookies", context)):
            return False, None

        if not (observer_cookie := cookies.get("observer")):
            return False, None

        try:
            if (
                mode := unsign_cookie_value("observer", observer_cookie, default=None)
            ) in ("view", "sample"):
                return True, mode
        except Exception as e:
            logger.warning("Failed to unsign observer cookie: %s", e)

        return False, None

    def shutdown(self):
        """Cleanup when shutting down."""
        with self._traces_lock:
            self._traces.clear()
        self._exporter.shutdown()

    def force_flush(self, timeout_millis=None):
        """Required by SpanProcessor interface."""
        return True
