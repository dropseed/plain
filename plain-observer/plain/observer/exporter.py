import logging
from datetime import UTC, datetime

from opentelemetry.sdk.trace.export import SpanExporter

from plain.models.observability import suppress_db_tracing
from plain.runtime import settings

logger = logging.getLogger(__name__)


class ObserverExporter(SpanExporter):
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
