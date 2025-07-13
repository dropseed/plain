from __future__ import annotations

import json
import logging
import re

from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind

from plain.models.observability import suppress_tracing
from plain.runtime import settings

logger = logging.getLogger(__name__)


def has_existing_trace_provider() -> bool:
    """Check if there is an existing trace provider."""
    current_provider = trace.get_tracer_provider()
    return current_provider and not isinstance(
        current_provider, trace.ProxyTracerProvider
    )


def setup_debug_trace_provider() -> None:
    sampler = PlainRequestSampler()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(BatchSpanProcessor(ObserveModelsExporter()))
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
        self._delegate = sampling.ParentBased(sampling.ALWAYS_ON)

        # TODO ignore url namespace instead? admin, observe, assets
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVE_IGNORE_URL_PATTERNS
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
        **kwargs,
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

        # Look for the "observe" cookie in the request and
        # sample if it is set to "true".
        if parent_context:
            if cookies := baggage.get_baggage("http.request.cookies", parent_context):
                # Using a signed cookie would be better -- only set by authed route
                if cookies.get("observe") == "true":
                    return sampling.SamplingResult(
                        sampling.Decision.RECORD_AND_SAMPLE,
                        attributes=attributes,
                    )
                else:
                    return sampling.SamplingResult(
                        sampling.Decision.DROP,
                        attributes=attributes,
                    )

        # Fallback to delegate sampler.
        return self._delegate.should_sample(
            parent_context,
            trace_id,
            name,
            kind,
            attributes,
            links,
            trace_state,
        )

    def get_description(self) -> str:
        return "PlainRequestSampler"


class ObserveModelsExporter(SpanExporter):
    """Exporter that writes spans into the observe models tables."""

    def export(self, spans):
        """Persist spans in bulk for efficiency."""

        from .models import Span, Trace

        with suppress_tracing():
            create_spans = []
            create_traces = {}

            for span in spans:
                span_data = json.loads(span.to_json())
                trace_id = span_data["context"]["trace_id"]

                # There should be at least one span with this attribute
                request_id = span_data["attributes"].get("plain.request.id", "")
                user_id = span_data["attributes"].get("user.id", "")
                session_id = span_data["attributes"].get("session.id", "")

                if not span_data["parent_id"]:
                    description = span_data["name"]
                else:
                    description = ""

                if trace := create_traces.get(trace_id):
                    if not trace.start_time:
                        trace.start_time = span_data["start_time"]
                    else:
                        trace.start_time = min(
                            trace.start_time, span_data["start_time"]
                        )

                    if not trace.end_time:
                        trace.end_time = span_data["end_time"]
                    else:
                        trace.end_time = max(trace.end_time, span_data["end_time"])

                    if not trace.request_id:
                        trace.request_id = request_id

                    if not trace.user_id:
                        trace.user_id = user_id

                    if not trace.session_id:
                        trace.session_id = session_id

                    if not trace.description:
                        trace.description = description
                else:
                    trace = Trace(
                        trace_id=trace_id,
                        start_time=span_data["start_time"],
                        end_time=span_data["end_time"],
                        request_id=request_id,
                        user_id=user_id,
                        session_id=session_id,
                        description=description,
                    )
                    create_traces[trace_id] = trace

                create_spans.append(
                    Span(
                        trace=trace,
                        span_id=span_data["context"]["span_id"],
                        name=span_data["name"],
                        kind=span_data["kind"],
                        parent_id=span_data["parent_id"] or "",
                        start_time=span_data["start_time"],
                        end_time=span_data["end_time"],
                        status=span_data["status"],
                        context=span_data["context"],
                        attributes=span_data["attributes"],
                        events=span_data["events"],
                        links=span_data["links"],
                        resource=span_data["resource"],
                    )
                )

            try:
                Trace.objects.bulk_create(
                    create_traces.values()
                )  # , update_conflicts=True, update_fields=["start_time", "end_time", "request_id"])
                Span.objects.bulk_create(create_spans)
            except Exception as e:
                logger.error(
                    "Failed to export spans to database: %s",
                    e,
                    exc_info=True,
                )

            # Delete oldest traces if we exceed the limit
            if Trace.objects.count() > settings.OBSERVE_TRACE_LIMIT:
                delete_ids = Trace.objects.order_by("start_time")[
                    : settings.OBSERVE_TRACE_LIMIT
                ].values_list("id", flat=True)
                Trace.objects.filter(id__in=delete_ids).delete()

        return True
