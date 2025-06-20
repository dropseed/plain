from __future__ import annotations

import json
import re
from collections.abc import Sequence

from opentelemetry.sdk.trace import sampling
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind

from plain.models.observability import suppress_tracing


class PlainRequestSampler(sampling.Sampler):
    """Drops traces based on request path or user role."""

    def __init__(
        self, delegate: sampling.Sampler, ignore_url_paths: Sequence[re.Pattern]
    ):
        self._delegate = delegate
        self._ignore_url_paths = ignore_url_paths

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
    ):  # type: ignore[override]
        # Can we get the request path from the context or something instead of contextvar?
        # not sure what to do with is_admin and stuff then...

        if attributes:
            if url_path := attributes[url_attributes.URL_PATH]:
                print("SHIT", url_path)
                for pattern in self._ignore_url_paths:
                    if pattern.match(url_path):
                        return sampling.SamplingResult(sampling.Decision.DROP)

            # Example rule: drop staff/admin requests entirely.
            # if getattr(request, "user", None) and getattr(request.user, "is_staff", False):
            #     return sampling.SamplingResult(sampling.Decision.DROP)

        # In dev we always sample?

        # Otherwise need an option to sample if session sampling enabled and is_admin

        # does empty parent context tell us we're at a root, and only check this there?
        # maybe is_admin should be an attribute, and observe_enabled could be an attribute

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

    def export(self, spans):  # type: ignore[override]
        """Persist spans in bulk for efficiency."""

        from .models import Span, Trace

        with suppress_tracing():
            create_spans = []
            create_traces = {}

            for span in spans:
                span_data = json.loads(span.to_json())
                trace_id = span_data["context"]["trace_id"]

                # There should be at least one span with this attribute
                request_id = span_data["attributes"].get("plain.request_id", "")

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
                else:
                    trace = Trace(
                        trace_id=trace_id,
                        start_time=span_data["start_time"],
                        end_time=span_data["end_time"],
                        request_id=request_id,
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

            # Trace.objects.bulk_create(
            #     create_traces.values()
            # )  # , update_conflicts=True, update_fields=["start_time", "end_time", "request_id"])
            # Span.objects.bulk_create(create_spans)

            # TODO could delete old spans and stuff here instead of chore? or both?
            # should be days based for sure (i.e. 30 days)
            # could also be limit based as a fallback

        return True
