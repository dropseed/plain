from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from datetime import UTC, datetime

from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider, sampling
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind

from plain.http.cookie import unsign_cookie_value
from plain.models.observability import suppress_db_tracing
from plain.runtime import settings

logger = logging.getLogger(__name__)


def get_span_collector():
    """Get the span collector instance from the tracer provider."""
    current_provider = trace.get_tracer_provider()
    if not current_provider or isinstance(current_provider, trace.ProxyTracerProvider):
        return None

    # Look for ObserveSpanProcessor in the span processors
    # Check if the provider has a _active_span_processor attribute
    if hasattr(current_provider, "_active_span_processor"):
        # It's a composite processor, check its _span_processors
        composite_processor = current_provider._active_span_processor
        if hasattr(composite_processor, "_span_processors"):
            for processor in composite_processor._span_processors:
                if isinstance(processor, ObserveSpanProcessor):
                    return processor

    return None


def has_existing_trace_provider() -> bool:
    """Check if there is an existing trace provider."""
    current_provider = trace.get_tracer_provider()
    return current_provider and not isinstance(
        current_provider, trace.ProxyTracerProvider
    )


def setup_debug_trace_provider() -> None:
    sampler = PlainRequestSampler()
    provider = TracerProvider(sampler=sampler)

    # Add the real-time span collector for immediate access
    span_collector = ObserveSpanProcessor()
    provider.add_span_processor(span_collector)

    # Add the database exporter using SimpleSpanProcessor for immediate export
    provider.add_span_processor(SimpleSpanProcessor(ObserveModelsExporter()))

    trace.set_tracer_provider(provider)


def is_debug_trace_provider() -> bool:
    """Check if the current trace provider is the debug trace provider."""
    current_provider = trace.get_tracer_provider()
    if current_provider and current_provider.sampler is not None:
        return isinstance(current_provider.sampler, PlainRequestSampler)
    return False


class PlainRequestSampler(sampling.Sampler):
    """Drops traces based on request path or user role."""

    def __init__(self):
        # Custom parent-based sampler that properly handles RECORD_ONLY inheritance
        self._delegate = sampling.ParentBased(sampling.ALWAYS_ON)

        # TODO ignore url namespace instead? admin, observe, assets
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVE_IGNORE_URL_PATTERNS
        ]

        # Track sampling decisions by trace ID
        self._trace_decisions = {}  # trace_id -> Decision
        self._lock = threading.Lock()

    def should_sample(
        self,
        parent_context,
        trace_id,
        name,
        kind: SpanKind | None = None,
        attributes=None,
        links=None,
        trace_state=None,
    ):
        # First, drop if the URL should be ignored.
        if attributes:
            if url_path := attributes.get(url_attributes.URL_PATH, ""):
                for pattern in self._ignore_url_paths:
                    if pattern.match(url_path):
                        return sampling.SamplingResult(
                            sampling.Decision.DROP,
                            attributes=attributes,
                        )

        # Check if we already have a decision for this trace
        with self._lock:
            if trace_id in self._trace_decisions:
                decision = self._trace_decisions[trace_id]
                return sampling.SamplingResult(
                    decision,
                    attributes=attributes,
                )

        # For new traces, check cookies in the context
        decision = None
        if parent_context:
            # Check cookies for root spans
            if cookies := baggage.get_baggage("http.request.cookies", parent_context):
                if observe_cookie := cookies.get("observe"):
                    unsigned_value = unsign_cookie_value(
                        "observe", observe_cookie, default=False
                    )

                    if unsigned_value == "sample":
                        decision = sampling.Decision.RECORD_AND_SAMPLE
                    elif unsigned_value == "record":
                        decision = sampling.Decision.RECORD_ONLY

                if decision is None:
                    decision = sampling.Decision.DROP

        # If no decision from cookies, use default
        if decision is None:
            result = self._delegate.should_sample(
                parent_context,
                trace_id,
                name,
                kind=kind,
                attributes=attributes,
                links=links,
                trace_state=trace_state,
            )
            decision = result.decision

        # Store the decision for this trace
        with self._lock:
            self._trace_decisions[trace_id] = decision
            # Clean up old entries if too many (simple LRU)
            if len(self._trace_decisions) > 1000:
                # Remove oldest entries
                for old_trace_id in list(self._trace_decisions.keys())[:100]:
                    del self._trace_decisions[old_trace_id]

        return sampling.SamplingResult(
            decision,
            attributes=attributes,
        )

    def get_description(self) -> str:
        return "PlainRequestSampler"


class ObserveSpanProcessor(SpanProcessor):
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


class ObserveModelsExporter(SpanExporter):
    """Exporter that writes spans into the observe models tables.

    Note: This should only receive spans with RECORD_AND_SAMPLE sampling decision.
    Spans with RECORD_ONLY should not reach this exporter.
    """

    def export(self, spans):
        """Persist each span individually for immediate export."""

        from .models import Span, Trace

        with suppress_db_tracing():
            for span in spans:
                try:
                    # Format IDs according to W3C Trace Context specification
                    trace_id_hex = format(span.get_span_context().trace_id, "032x")
                    span_id_hex = format(span.get_span_context().span_id, "016x")
                    parent_id_hex = (
                        format(span.parent.span_id, "016x") if span.parent else ""
                    )

                    # Extract attributes directly
                    attributes = dict(span.attributes) if span.attributes else {}
                    request_id = attributes.get("plain.request.id", "")
                    user_id = attributes.get("user.id", "")
                    session_id = attributes.get("session.id", "")

                    # Set description for root spans
                    description = span.name if not parent_id_hex else ""

                    # Convert timestamps from nanoseconds to datetime
                    start_time = (
                        datetime.fromtimestamp(span.start_time / 1_000_000_000, tz=UTC)
                        if span.start_time
                        else None
                    )
                    end_time = (
                        datetime.fromtimestamp(span.end_time / 1_000_000_000, tz=UTC)
                        if span.end_time
                        else None
                    )

                    # Get or create the trace
                    trace, created = Trace.objects.get_or_create(
                        trace_id=trace_id_hex,
                        defaults={
                            "start_time": start_time,
                            "end_time": end_time,
                            "request_id": request_id,
                            "user_id": user_id,
                            "session_id": session_id,
                            "description": description,
                        },
                    )

                    # Update trace if we have better data
                    if not created:
                        updated = False
                        if start_time and (
                            not trace.start_time or start_time < trace.start_time
                        ):
                            trace.start_time = start_time
                            updated = True
                        if end_time and (
                            not trace.end_time or end_time > trace.end_time
                        ):
                            trace.end_time = end_time
                            updated = True
                        if request_id and not trace.request_id:
                            trace.request_id = request_id
                            updated = True
                        if user_id and not trace.user_id:
                            trace.user_id = user_id
                            updated = True
                        if session_id and not trace.session_id:
                            trace.session_id = session_id
                            updated = True
                        if description and not trace.description:
                            trace.description = description
                            updated = True
                        if updated:
                            trace.save()

                    # Extract span kind directly from the span object
                    kind_str = span.kind.name if span.kind else "INTERNAL"

                    # Convert events to JSON format
                    events_json = []
                    if span.events:
                        for event in span.events:
                            events_json.append(
                                {
                                    "name": event.name,
                                    "timestamp": event.timestamp,
                                    "attributes": (
                                        dict(event.attributes)
                                        if event.attributes
                                        else {}
                                    ),
                                }
                            )

                    # Convert links to JSON format
                    links_json = []
                    if span.links:
                        for link in span.links:
                            links_json.append(
                                {
                                    "context": {
                                        "trace_id": format(
                                            link.context.trace_id, "032x"
                                        ),
                                        "span_id": format(link.context.span_id, "016x"),
                                    },
                                    "attributes": (
                                        dict(link.attributes) if link.attributes else {}
                                    ),
                                }
                            )

                    # Create the span
                    Span.objects.get_or_create(
                        trace=trace,
                        span_id=span_id_hex,
                        defaults={
                            "name": span.name,
                            "kind": kind_str,
                            "parent_id": parent_id_hex,
                            "start_time": start_time,
                            "end_time": end_time,
                            "status": {
                                "status_code": (
                                    span.status.status_code.name
                                    if span.status
                                    else "UNSET"
                                ),
                                "description": span.status.description
                                if span.status
                                else "",
                            },
                            "context": {
                                "trace_id": trace_id_hex,
                                "span_id": span_id_hex,
                                "trace_flags": span.get_span_context().trace_flags,
                                "trace_state": (
                                    dict(span.get_span_context().trace_state)
                                    if span.get_span_context().trace_state
                                    else {}
                                ),
                            },
                            "attributes": attributes,
                            "events": events_json,
                            "links": links_json,
                            "resource": (
                                dict(span.resource.attributes) if span.resource else {}
                            ),
                        },
                    )

                except Exception as e:
                    logger.warning(
                        "Failed to export span to database: %s",
                        e,
                        exc_info=True,
                    )

            # Delete oldest traces if we exceed the limit
            try:
                if Trace.objects.count() > settings.OBSERVE_TRACE_LIMIT:
                    delete_ids = Trace.objects.order_by("start_time")[
                        : settings.OBSERVE_TRACE_LIMIT
                    ].values_list("id", flat=True)
                    Trace.objects.filter(id__in=delete_ids).delete()
            except Exception as e:
                logger.warning("Failed to clean up old traces: %s", e)

        return True
