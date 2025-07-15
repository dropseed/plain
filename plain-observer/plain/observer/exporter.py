import logging
from datetime import UTC, datetime

from opentelemetry.sdk.trace.export import SpanExporter

from plain.models.observability import suppress_db_tracing
from plain.runtime import settings

logger = logging.getLogger(__name__)


class ObserverExporter(SpanExporter):
    """Exporter that writes spans into the observe models tables.

    This exporter only receives spans that have been sampled (RECORD_AND_SAMPLE decision).
    Spans that are only being viewed in real-time are kept in memory by the ObserverSpanProcessor.
    """

    def export(self, spans):
        """Persist spans in bulk for a completed trace."""

        from .models import Span, Trace

        if not spans:
            return True

        with suppress_db_tracing():
            try:
                # Get trace information from the first span
                first_span = spans[0]
                trace_id_hex = format(first_span.get_span_context().trace_id, "032x")

                # Find trace boundaries and root span info
                earliest_start = None
                latest_end = None
                root_span = None
                request_id = ""
                user_id = ""
                session_id = ""

                for span in spans:
                    if span.start_time and (
                        earliest_start is None or span.start_time < earliest_start
                    ):
                        earliest_start = span.start_time
                    if span.end_time and (
                        latest_end is None or span.end_time > latest_end
                    ):
                        latest_end = span.end_time

                    # Get trace-level attributes from root span
                    if not span.parent:
                        root_span = span
                        if span.attributes:
                            request_id = span.attributes.get("plain.request.id", "")
                            user_id = span.attributes.get("user.id", "")
                            session_id = span.attributes.get("session.id", "")

                # Convert timestamps
                start_time = (
                    datetime.fromtimestamp(earliest_start / 1_000_000_000, tz=UTC)
                    if earliest_start
                    else None
                )
                end_time = (
                    datetime.fromtimestamp(latest_end / 1_000_000_000, tz=UTC)
                    if latest_end
                    else None
                )

                # Create or update trace
                trace, created = Trace.objects.update_or_create(
                    trace_id=trace_id_hex,
                    defaults={
                        "start_time": start_time,
                        "end_time": end_time,
                        "request_id": request_id,
                        "user_id": user_id,
                        "session_id": session_id,
                        "description": root_span.name if root_span else "",
                    },
                )

                # Prepare span objects for bulk creation
                span_objs = []
                for span in spans:
                    span_id_hex = format(span.get_span_context().span_id, "016x")
                    parent_id_hex = (
                        format(span.parent.span_id, "016x") if span.parent else ""
                    )

                    # Convert timestamps
                    span_start = (
                        datetime.fromtimestamp(span.start_time / 1_000_000_000, tz=UTC)
                        if span.start_time
                        else None
                    )
                    span_end = (
                        datetime.fromtimestamp(span.end_time / 1_000_000_000, tz=UTC)
                        if span.end_time
                        else None
                    )

                    # Extract attributes
                    attributes = dict(span.attributes) if span.attributes else {}

                    # Convert events to JSON format
                    events_json = []
                    if span.events:
                        for event in span.events:
                            events_json.append(
                                {
                                    "name": event.name,
                                    "timestamp": event.timestamp,
                                    "attributes": dict(event.attributes)
                                    if event.attributes
                                    else {},
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
                                    "attributes": dict(link.attributes)
                                    if link.attributes
                                    else {},
                                }
                            )

                    span_objs.append(
                        Span(
                            trace=trace,
                            span_id=span_id_hex,
                            name=span.name,
                            kind=span.kind.name if span.kind else "INTERNAL",
                            parent_id=parent_id_hex,
                            start_time=span_start,
                            end_time=span_end,
                            status={
                                "status_code": span.status.status_code.name
                                if span.status
                                else "UNSET",
                                "description": span.status.description
                                if span.status
                                else "",
                            },
                            context={
                                "trace_id": trace_id_hex,
                                "span_id": span_id_hex,
                                "trace_flags": span.get_span_context().trace_flags,
                                "trace_state": dict(span.get_span_context().trace_state)
                                if span.get_span_context().trace_state
                                else {},
                            },
                            attributes=attributes,
                            events=events_json,
                            links=links_json,
                            resource=dict(span.resource.attributes)
                            if span.resource
                            else {},
                        )
                    )

                # Bulk create spans
                logger.info(
                    "Bulk creating %d spans for trace %s", len(span_objs), trace_id_hex
                )
                Span.objects.bulk_create(span_objs)

            except Exception as e:
                logger.warning(
                    "Failed to export trace to database: %s",
                    e,
                    exc_info=True,
                )

            # Delete oldest traces if we exceed the limit
            try:
                if Trace.objects.count() > settings.OBSERVER_TRACE_LIMIT:
                    delete_ids = Trace.objects.order_by("start_time")[
                        : settings.OBSERVER_TRACE_LIMIT
                    ].values_list("id", flat=True)
                    Trace.objects.filter(id__in=delete_ids).delete()
            except Exception as e:
                logger.warning(
                    "Failed to update observer traces in db: %s", e, exc_info=True
                )

        return True

    def shutdown(self):
        """Called when the SDK is shut down."""
        pass
