from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from collections.abc import MutableMapping, Sequence
from typing import TYPE_CHECKING, Any, cast

import opentelemetry.context as context_api
from opentelemetry import baggage, trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, sampling
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import (
    Link,
    SpanKind,
    TraceState,
    format_span_id,
    format_trace_id,
)

from plain.http.cookie import unsign_cookie_value
from plain.logs import app_logger
from plain.models.otel import suppress_db_tracing
from plain.runtime import settings

from .core import Observer, ObserverMode

if TYPE_CHECKING:
    from plain.observer.models import Span as ObserverSpanModel
    from plain.observer.models import Trace as TraceModel

    from .logging import ObserverLogEntry

logger = logging.getLogger(__name__)


def get_observer_span_processor() -> ObserverSpanProcessor | None:
    """Get the span collector instance from the tracer provider."""
    if not (current_provider := trace.get_tracer_provider()):
        return None

    # Look for ObserverSpanProcessor in the span processors
    # Check if the provider has a _active_span_processor attribute
    if hasattr(current_provider, "_active_span_processor"):
        # It's a composite processor, check its _span_processors
        if composite_processor := current_provider._active_span_processor:
            if hasattr(composite_processor, "_span_processors"):
                processors = cast(
                    Sequence[SpanProcessor],
                    getattr(composite_processor, "_span_processors", ()),
                )
                for processor in processors:
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

    def __init__(self) -> None:
        # Custom parent-based sampler
        self._delegate = sampling.ParentBased(sampling.ALWAYS_OFF)

        # TODO ignore url namespace instead? admin, observer, assets
        self._ignore_url_paths: list[re.Pattern[str]] = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: MutableMapping[str, Any] | None = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> sampling.SamplingResult:
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
        decision: sampling.Decision | None = None
        if parent_context:
            # Check cookies for sampling decision
            cookies = cast(
                MutableMapping[str, str] | None,
                baggage.get_baggage("http.request.cookies", parent_context),
            )
            if cookies and (observer_cookie := cookies.get(Observer.COOKIE_NAME)):
                unsigned_value = unsign_cookie_value(
                    Observer.COOKIE_NAME, observer_cookie, default=None
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

    def __init__(self, primary: sampling.Sampler, secondary: sampling.Sampler) -> None:
        self.primary = primary
        self.secondary = secondary

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: MutableMapping[str, Any] | None = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> sampling.SamplingResult:
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

    def __init__(self) -> None:
        # Span storage
        self._traces: defaultdict[str, dict[str, Any]] = defaultdict(
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
        self._ignore_url_paths: list[re.Pattern[str]] = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

    def on_start(self, span: Any, parent_context: Context | None = None) -> None:
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

            span_id = f"0x{format_span_id(span.get_span_context().span_id)}"

            # Enable DEBUG logging only for PERSIST mode (when logs are captured)
            if trace_info["mode"] == ObserverMode.PERSIST.value:
                app_logger.debug_mode.start()

            # Store span (we know mode is truthy if we get here)
            trace_info["active_otel_spans"][span_id] = span

            # Track root span
            if not span.parent:
                trace_info["root_span_id"] = span_id

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span ends."""
        trace_id = f"0x{format_trace_id(span.get_span_context().trace_id)}"
        span_id = f"0x{format_span_id(span.get_span_context().span_id)}"

        with self._traces_lock:
            # Skip if we don't have this trace (mode was None on start)
            if trace_id not in self._traces:
                return

            trace_info = self._traces[trace_id]

            # Disable DEBUG logging only for PERSIST mode spans
            if trace_info["mode"] == ObserverMode.PERSIST.value:
                app_logger.debug_mode.end()

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
                    # Get and remove logs for this trace
                    from .logging import observer_log_handler

                    if observer_log_handler:
                        logs = observer_log_handler.pop_logs_for_trace(trace_id)
                    else:
                        logs = []

                    logger.debug(
                        "Exporting %d spans and %d logs for trace %s",
                        len(trace_info["span_models"]),
                        len(logs),
                        trace_id,
                    )
                    # The trace is done now, so we can get a more accurate summary
                    trace_info["trace"].summary = trace_info["trace"].get_trace_summary(
                        trace_info["span_models"]
                    )
                    self._export_trace(
                        trace=trace_info["trace"],
                        spans=trace_info["span_models"],
                        logs=logs,
                    )

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

    def _export_trace(
        self,
        *,
        trace: TraceModel,
        spans: Sequence[ObserverSpanModel],
        logs: Sequence[ObserverLogEntry],
    ) -> None:
        """Export trace, spans, and logs to the database."""
        from .models import Log, Span, Trace

        with suppress_db_tracing():
            try:
                trace.save()

                for span in spans:
                    span.trace = trace

                # Bulk create spans
                Span.query.bulk_create(spans)  # type: ignore[arg-type]

                # Create log models if we have logs
                if logs:
                    # Create a mapping of span_id to span_model
                    span_id_to_model = {
                        span_model.span_id: span_model for span_model in spans
                    }

                    log_models = []
                    for log_entry in logs:
                        log_model = Log(
                            trace=trace,
                            timestamp=log_entry["timestamp"],
                            level=log_entry["level"],
                            message=log_entry["message"],
                            span=span_id_to_model.get(log_entry["span_id"]),
                        )
                        log_models.append(log_model)

                    Log.query.bulk_create(log_models)

            except Exception as e:
                logger.warning(
                    "Failed to export trace to database: %s",
                    e,
                    exc_info=True,
                )

            # Delete oldest traces if we exceed the limit
            if settings.OBSERVER_TRACE_LIMIT > 0:
                try:
                    if Trace.query.count() > settings.OBSERVER_TRACE_LIMIT:
                        excess_count = (
                            Trace.query.count() - settings.OBSERVER_TRACE_LIMIT
                        )
                        delete_ids = Trace.query.order_by("start_time")[
                            :excess_count
                        ].values_list("id", flat=True)
                        Trace.query.filter(id__in=delete_ids).delete()
                except Exception as e:
                    logger.warning(
                        "Failed to clean up old observer traces: %s", e, exc_info=True
                    )

    def _get_recording_mode(
        self, span: Any, parent_context: Context | None
    ) -> str | None:
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

                with suppress_db_tracing():
                    if Span.query.filter(
                        span_id=f"0x{format_span_id(link.context.span_id)}"
                    ).exists():
                        return ObserverMode.PERSIST.value

        if not (context := parent_context or context_api.get_current()):
            return None

        cookies = cast(
            MutableMapping[str, str] | None,
            baggage.get_baggage("http.request.cookies", context),
        )
        if not cookies:
            return None

        observer_cookie = cookies.get(Observer.COOKIE_NAME)
        if not observer_cookie:
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

    def shutdown(self) -> None:
        """Cleanup when shutting down."""
        with self._traces_lock:
            self._traces.clear()

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """Required by SpanProcessor interface."""
        return True
