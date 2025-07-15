import threading
from collections import defaultdict

from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor


def get_span_processor():
    """Get the span collector instance from the tracer provider."""
    current_provider = trace.get_tracer_provider()
    if not current_provider:
        return None

    # Look for ObserverSpanProcessor in the span processors
    # Check if the provider has a _active_span_processor attribute
    if hasattr(current_provider, "_active_span_processor"):
        # It's a composite processor, check its _span_processors
        composite_processor = current_provider._active_span_processor
        if hasattr(composite_processor, "_span_processors"):
            for processor in composite_processor._span_processors:
                if isinstance(processor, ObserverSpanProcessor):
                    return processor

    return None


class ObserverSpanProcessor(SpanProcessor):
    """Collects spans in real-time for current trace performance monitoring."""

    def __init__(self):
        self.active_spans_by_trace = defaultdict(dict)  # trace_id -> {span_id: span}
        self.completed_spans_by_trace = defaultdict(list)  # trace_id -> [spans]
        self.lock = threading.Lock()

    def on_start(self, span, parent_context=None):
        """Called when a span starts."""
        with self.lock:
            trace_id = format(span.get_span_context().trace_id, "032x")
            span_id = format(span.get_span_context().span_id, "016x")
            self.active_spans_by_trace[trace_id][span_id] = span

    def on_end(self, span):
        """Called when a span ends."""
        with self.lock:
            trace_id = format(span.get_span_context().trace_id, "032x")
            span_id = format(span.get_span_context().span_id, "016x")

            # Move from active to completed
            if trace_id in self.active_spans_by_trace:
                span_obj = self.active_spans_by_trace[trace_id].pop(span_id, None)
                if span_obj:
                    self.completed_spans_by_trace[trace_id].append(span_obj)

                # Clean up empty trace entries
                if not self.active_spans_by_trace[trace_id]:
                    del self.active_spans_by_trace[trace_id]

    def get_current_trace_summary(self):
        """Get performance summary for the currently active trace."""
        current_span = trace.get_current_span()
        if not current_span:
            # If no current span, check if we have any active traces at all
            with self.lock:
                if not self.active_spans_by_trace and not self.completed_spans_by_trace:
                    return None

                # Get the most recent trace if we can't find current span
                all_trace_ids = list(self.active_spans_by_trace.keys()) + list(
                    self.completed_spans_by_trace.keys()
                )
                if not all_trace_ids:
                    return None
                trace_id = all_trace_ids[-1]  # Use most recent
        else:
            # Use the current span's trace
            trace_id = format(current_span.get_span_context().trace_id, "032x")

        with self.lock:
            active_spans = list(self.active_spans_by_trace.get(trace_id, {}).values())
            completed_spans = self.completed_spans_by_trace.get(trace_id, [])
            all_spans = active_spans + completed_spans

            if not all_spans:
                return None

            # Calculate summary stats
            db_queries = 0
            total_spans = len(all_spans)
            earliest_start = None
            latest_end = None

            for span in all_spans:
                # Count DB queries
                if span.attributes and span.attributes.get("db.system"):
                    db_queries += 1

                # Calculate duration for completed spans
                if span.end_time and span.start_time:
                    if earliest_start is None or span.start_time < earliest_start:
                        earliest_start = span.start_time

                    if latest_end is None or span.end_time > latest_end:
                        latest_end = span.end_time
                elif span.start_time:
                    # For active spans, track start time
                    if earliest_start is None or span.start_time < earliest_start:
                        earliest_start = span.start_time

            # Calculate overall duration (for the whole trace)
            duration_ms = 0.0
            if earliest_start and latest_end:
                duration_ms = (latest_end - earliest_start) / 1_000_000  # ns to ms
            elif earliest_start:
                # If trace is still active, calculate duration so far
                import time

                current_time_ns = int(time.time() * 1_000_000_000)
                duration_ms = (current_time_ns - earliest_start) / 1_000_000

            # Build summary parts like the Trace model does
            parts = [f"{total_spans}sp"]

            if db_queries > 0:
                parts.append(f"{db_queries}db")

            if duration_ms > 0:
                parts.append(f"{round(duration_ms, 1)}ms")

            return " ".join(parts)

    def shutdown(self):
        """Cleanup when shutting down."""
        with self.lock:
            self.active_spans_by_trace.clear()
            self.completed_spans_by_trace.clear()

    def force_flush(self, timeout_millis=None):
        """Required by SpanProcessor interface."""
        return True
