import logging
import re
import threading
from collections import defaultdict

import opentelemetry.context as context_api
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import SpanProcessor, sampling
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind, format_span_id, format_trace_id

from plain.http.cookie import unsign_cookie_value
from plain.models.otel import suppress_db_tracing
from plain.runtime import settings

from .core import Observer, ObserverMode

logger = logging.getLogger(__name__)


def get_observer_span_processor():
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

    if not (processor := get_observer_span_processor()):
        return None

    trace_id = f"0x{format_trace_id(current_span.get_span_context().trace_id)}"

    # Technically we're still in the trace... so the duration and stuff could shift slightly
    # (though we should be at the end of the template, hopefully)
    return processor.get_trace_summary(trace_id)


class ObserverSampler(sampling.Sampler):
    """Samples traces based on request path and cookies."""

    def __init__(self):
        # Custom parent-based sampler
        self._delegate = sampling.ParentBased(sampling.ALWAYS_OFF)

        # TODO ignore url namespace instead? admin, observer, assets
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

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

        # If no processor decision, check cookies directly for root spans
        decision = None
        if parent_context:
            # Check cookies for sampling decision
            if cookies := baggage.get_baggage("http.request.cookies", parent_context):
                if observer_cookie := cookies.get(Observer.COOKIE_NAME):
                    unsigned_value = unsign_cookie_value(
                        Observer.COOKIE_NAME, observer_cookie, default=False
                    )

                    if unsigned_value in (
                        ObserverMode.PERSIST.value,
                        ObserverMode.SUMMARY.value,
                    ):
                        # Always use RECORD_AND_SAMPLE so ParentBased works correctly
                        # The processor will check the mode to decide whether to export
                        decision = sampling.Decision.RECORD_AND_SAMPLE
                    else:
                        decision = sampling.Decision.DROP

        # If there are links, assume it is to another trace/span that we are keeping
        if links:
            decision = sampling.Decision.RECORD_AND_SAMPLE

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

        return sampling.SamplingResult(
            decision,
            attributes=attributes,
        )

    def get_description(self) -> str:
        return "ObserverSampler"


class ObserverCombinedSampler(sampling.Sampler):
    """Combine another sampler with ``ObserverSampler``."""

    def __init__(self, primary: sampling.Sampler, secondary: sampling.Sampler):
        self.primary = primary
        self.secondary = secondary

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
        result = self.primary.should_sample(
            parent_context,
            trace_id,
            name,
            kind=kind,
            attributes=attributes,
            links=links,
            trace_state=trace_state,
        )

        if result.decision is sampling.Decision.DROP:
            return self.secondary.should_sample(
                parent_context,
                trace_id,
                name,
                kind=kind,
                attributes=attributes,
                links=links,
                trace_state=trace_state,
            )

        return result

    def get_description(self) -> str:
        return f"ObserverCombinedSampler({self.primary.get_description()}, {self.secondary.get_description()})"


class ObserverSpanProcessor(SpanProcessor):
    """Collects spans in real-time for current trace performance monitoring.

    This processor keeps spans in memory for traces that have the 'summary' or 'persist'
    cookie set. These spans can be accessed via get_current_trace_summary() for
    real-time debugging. Spans with 'persist' cookie will also be persisted to the
    database.
    """

    def __init__(self):
        # Span storage
        self._traces = defaultdict(
            lambda: {
                "trace": None,  # Trace model instance
                "active_otel_spans": {},  # span_id -> opentelemetry span
                "completed_otel_spans": [],  # list of opentelemetry spans
                "span_models": [],  # list of Span model instances
                "root_span_id": None,
                "mode": None,  # None, ObserverMode.SUMMARY.value, or ObserverMode.PERSIST.value
            }
        )
        self._traces_lock = threading.Lock()
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

    def on_start(self, span, parent_context=None):
        """Called when a span starts."""
        trace_id = f"0x{format_trace_id(span.get_span_context().trace_id)}"

        with self._traces_lock:
            # Check if we already have this trace
            if trace_id in self._traces:
                trace_info = self._traces[trace_id]
            else:
                # First span in trace - determine if we should record it
                mode = self._get_recording_mode(span, parent_context)
                if not mode:
                    # Don't create trace entry for traces we won't record
                    return

                # Create trace entry only for traces we'll record
                trace_info = self._traces[trace_id]
                trace_info["mode"] = mode

                # Clean up old traces if too many
                if len(self._traces) > 1000:
                    # Remove oldest 100 traces
                    oldest_ids = sorted(self._traces.keys())[:100]
                    for old_id in oldest_ids:
                        del self._traces[old_id]

            span_id = f"0x{format_span_id(span.get_span_context().span_id)}"

            # Store span (we know mode is truthy if we get here)
            trace_info["active_otel_spans"][span_id] = span

            # Track root span
            if not span.parent:
                trace_info["root_span_id"] = span_id

    def on_end(self, span):
        """Called when a span ends."""
        trace_id = f"0x{format_trace_id(span.get_span_context().trace_id)}"
        span_id = f"0x{format_span_id(span.get_span_context().span_id)}"

        with self._traces_lock:
            # Skip if we don't have this trace (mode was None on start)
            if trace_id not in self._traces:
                return

            trace_info = self._traces[trace_id]

            # Move span from active to completed
            if trace_info["active_otel_spans"].pop(span_id, None):
                trace_info["completed_otel_spans"].append(span)

            # Check if trace is complete (root span ended)
            if span_id == trace_info["root_span_id"]:
                all_spans = trace_info["completed_otel_spans"]

                from .models import Span, Trace

                trace_info["trace"] = Trace.from_opentelemetry_spans(all_spans)
                trace_info["span_models"] = [
                    Span.from_opentelemetry_span(s, trace_info["trace"])
                    for s in all_spans
                ]

                # Export if in persist mode
                if trace_info["mode"] == ObserverMode.PERSIST.value:
                    logger.debug(
                        "Exporting %d spans for trace %s",
                        len(trace_info["span_models"]),
                        trace_id,
                    )
                    # The trace is done now, so we can get a more accurate summary
                    trace_info["trace"].summary = trace_info["trace"].get_trace_summary(
                        trace_info["span_models"]
                    )
                    self._export_trace(trace_info["trace"], trace_info["span_models"])

                # Clean up trace
                del self._traces[trace_id]

    def get_trace_summary(self, trace_id: str) -> str | None:
        """Get performance summary for a specific trace."""
        from .models import Span, Trace

        with self._traces_lock:
            # Return None if trace doesn't exist (mode was None)
            if trace_id not in self._traces:
                return None

            trace_info = self._traces[trace_id]

            # Combine active and completed spans
            all_otel_spans = (
                list(trace_info["active_otel_spans"].values())
                + trace_info["completed_otel_spans"]
            )

            if not all_otel_spans:
                return None

            # Create or update trace model instance
            if not trace_info["trace"]:
                trace_info["trace"] = Trace.from_opentelemetry_spans(all_otel_spans)

            if not trace_info["trace"]:
                return None

            # Create span model instances if needed
            span_models = trace_info.get("span_models", [])
            if not span_models:
                span_models = [
                    Span.from_opentelemetry_span(s, trace_info["trace"])
                    for s in all_otel_spans
                ]

            return trace_info["trace"].get_trace_summary(span_models)

    def _export_trace(self, trace, span_models):
        """Export trace and spans to the database."""
        from .models import Span, Trace

        with suppress_db_tracing():
            try:
                trace.save()

                for span_model in span_models:
                    span_model.trace = trace

                # Bulk create spans
                Span.objects.bulk_create(span_models)
            except Exception as e:
                logger.warning(
                    "Failed to export trace to database: %s",
                    e,
                    exc_info=True,
                )

            # Delete oldest traces if we exceed the limit
            if settings.OBSERVER_TRACE_LIMIT > 0:
                try:
                    if Trace.objects.count() > settings.OBSERVER_TRACE_LIMIT:
                        delete_ids = Trace.objects.order_by("start_time")[
                            : settings.OBSERVER_TRACE_LIMIT
                        ].values_list("id", flat=True)
                        Trace.objects.filter(id__in=delete_ids).delete()
                except Exception as e:
                    logger.warning(
                        "Failed to clean up old observer traces: %s", e, exc_info=True
                    )

    def _get_recording_mode(self, span, parent_context) -> str | None:
        # Again check the span attributes, in case we relied on another sampler
        if span.attributes:
            if url_path := span.attributes.get(url_attributes.URL_PATH, ""):
                for pattern in self._ignore_url_paths:
                    if pattern.match(url_path):
                        return None

        # If the span has links, then we are going to export if the linked span is also exported
        for link in span.links:
            if link.context.is_valid and link.context.span_id:
                from .models import Span

                if Span.objects.filter(
                    span_id=f"0x{format_span_id(link.context.span_id)}"
                ).exists():
                    return ObserverMode.PERSIST.value

        if not (context := parent_context or context_api.get_current()):
            return None

        if not (cookies := baggage.get_baggage("http.request.cookies", context)):
            return None

        if not (observer_cookie := cookies.get(Observer.COOKIE_NAME)):
            return None

        try:
            mode = unsign_cookie_value(
                Observer.COOKIE_NAME, observer_cookie, default=None
            )
            if mode in (ObserverMode.SUMMARY.value, ObserverMode.PERSIST.value):
                return mode
        except Exception as e:
            logger.warning("Failed to unsign observer cookie: %s", e)

        return None

    def shutdown(self):
        """Cleanup when shutting down."""
        with self._traces_lock:
            self._traces.clear()

    def force_flush(self, timeout_millis=None):
        """Required by SpanProcessor interface."""
        return True
