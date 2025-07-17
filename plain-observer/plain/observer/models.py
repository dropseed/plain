import json
from datetime import UTC, datetime
from functools import cached_property

import sqlparse
from opentelemetry.semconv._incubating.attributes import (
    exception_attributes,
    session_attributes,
    user_attributes,
)
from opentelemetry.semconv.attributes import db_attributes

from plain import models


@models.register_model
class Trace(models.Model):
    trace_id = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    root_span_name = models.TextField(default="", required=False)

    # Plain fields
    request_id = models.CharField(max_length=255, default="", required=False)
    session_id = models.CharField(max_length=255, default="", required=False)
    user_id = models.CharField(max_length=255, default="", required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace_id"],
                name="observer_unique_trace_id",
            )
        ]

    def __str__(self):
        return self.trace_id

    def duration_ms(self):
        return (self.end_time - self.start_time).total_seconds() * 1000

    def get_trace_summary(self, spans=None):
        """Get a concise summary string for toolbar display.

        Args:
            spans: Optional list of span objects. If not provided, will query from database.
        """
        # Get spans from database if not provided
        if spans is None:
            spans = list(self.spans.all())

        if not spans:
            return ""

        # Count database queries and track duplicates
        query_counts = {}
        db_queries = 0

        for span in spans:
            if span.attributes.get(db_attributes.DB_SYSTEM_NAME):
                db_queries += 1
                if query_text := span.attributes.get(db_attributes.DB_QUERY_TEXT):
                    query_counts[query_text] = query_counts.get(query_text, 0) + 1

        # Count duplicate queries (queries that appear more than once)
        duplicate_count = sum(count - 1 for count in query_counts.values() if count > 1)

        # Build summary: "n spans, n queries (n duplicates), Xms"
        parts = []

        # Queries count with duplicates
        if db_queries > 0:
            query_part = f"{db_queries} quer{'y' if db_queries == 1 else 'ies'}"
            if duplicate_count > 0:
                query_part += f" ({duplicate_count} duplicate{'' if duplicate_count == 1 else 's'})"
            parts.append(query_part)

        # Duration
        if (duration_ms := self.duration_ms()) is not None:
            parts.append(f"{round(duration_ms, 1)}ms")

        return " • ".join(parts)

    @classmethod
    def from_opentelemetry_spans(cls, spans):
        """Create a Trace instance from a list of OpenTelemetry spans."""
        # Get trace information from the first span
        first_span = spans[0]
        trace_id = f"0x{first_span.get_span_context().trace_id:032x}"

        # Find trace boundaries and root span info
        earliest_start = None
        latest_end = None
        root_span = None
        request_id = ""
        user_id = ""
        session_id = ""

        for span in spans:
            if not span.parent:
                root_span = span

            if span.start_time and (
                earliest_start is None or span.start_time < earliest_start
            ):
                earliest_start = span.start_time
            # Only update latest_end if the span has actually ended
            if span.end_time and (latest_end is None or span.end_time > latest_end):
                latest_end = span.end_time

            # For OpenTelemetry spans, access attributes directly
            span_attrs = getattr(span, "attributes", {})
            request_id = request_id or span_attrs.get("plain.request.id", "")
            user_id = user_id or span_attrs.get(user_attributes.USER_ID, "")
            session_id = session_id or span_attrs.get(session_attributes.SESSION_ID, "")

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

        # Create trace instance
        # Note: end_time might be None if there are active spans
        # This is OK since this trace is only used for summaries, not persistence
        return cls(
            trace_id=trace_id,
            start_time=start_time,
            end_time=end_time
            or start_time,  # Use start_time as fallback for active traces
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            root_span_name=root_span.name if root_span else "",
        )

    def as_dict(self):
        spans = [span.span_data for span in self.spans.all().order_by("start_time")]

        return {
            "trace_id": self.trace_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms(),
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "spans": spans,
        }


@models.register_model
class Span(models.Model):
    trace = models.ForeignKey(Trace, on_delete=models.CASCADE, related_name="spans")

    span_id = models.CharField(max_length=255)

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)
    parent_id = models.CharField(max_length=255, default="", required=False)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=50, default="", required=False)
    span_data = models.JSONField(default=dict, required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace", "span_id"],
                name="observer_unique_span_id",
            )
        ]
        indexes = [
            models.Index(fields=["trace", "span_id"]),
            models.Index(fields=["trace"]),
            models.Index(fields=["start_time"]),
        ]

    @classmethod
    def from_opentelemetry_span(cls, otel_span, trace):
        """Create a Span instance from an OpenTelemetry span."""

        span_data = json.loads(otel_span.to_json())

        # Extract status code as string, default to empty string if unset
        status = ""
        if span_data.get("status") and span_data["status"].get("status_code"):
            status = span_data["status"]["status_code"]

        return cls(
            trace=trace,
            span_id=span_data["context"]["span_id"],
            name=span_data["name"],
            kind=span_data["kind"][len("SpanKind.") :],
            parent_id=span_data["parent_id"] or "",
            start_time=span_data["start_time"],
            end_time=span_data["end_time"],
            status=status,
            span_data=span_data,
        )

    def __str__(self):
        return self.span_id

    @property
    def attributes(self):
        """Get attributes from span_data."""
        return self.span_data.get("attributes", {})

    @property
    def events(self):
        """Get events from span_data."""
        return self.span_data.get("events", [])

    @property
    def links(self):
        """Get links from span_data."""
        return self.span_data.get("links", [])

    @property
    def resource(self):
        """Get resource from span_data."""
        return self.span_data.get("resource", {})

    @property
    def context(self):
        """Get context from span_data."""
        return self.span_data.get("context", {})

    def duration_ms(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    def description(self):
        if summary := self.attributes.get(db_attributes.DB_QUERY_SUMMARY):
            return summary
        if query := self.attributes.get(db_attributes.DB_QUERY_TEXT):
            return query
        return self.name

    @cached_property
    def sql_query(self):
        """Get the SQL query if this span contains one."""
        return self.attributes.get(db_attributes.DB_QUERY_TEXT)

    def get_formatted_sql(self):
        """Get the pretty-formatted SQL query if this span contains one."""
        sql = self.sql_query
        if not sql:
            return None

        return sqlparse.format(
            sql,
            reindent=True,
            keyword_case="upper",
            identifier_case="lower",
            strip_comments=False,
            strip_whitespace=True,
            indent_width=2,
            wrap_after=80,
            comma_first=False,
        )

    def format_event_timestamp(self, timestamp):
        """Convert event timestamp to a readable datetime."""
        if isinstance(timestamp, int | float):
            try:
                # Try as seconds first
                if timestamp > 1e10:  # Likely nanoseconds
                    timestamp = timestamp / 1e9
                elif timestamp > 1e7:  # Likely milliseconds
                    timestamp = timestamp / 1e3

                return datetime.fromtimestamp(timestamp, tz=UTC)
            except (ValueError, OSError):
                return str(timestamp)
        return timestamp

    def get_exception_stacktrace(self):
        """Get the exception stacktrace if this span has an exception event."""
        if not self.events:
            return None

        for event in self.events:
            if event.get("name") == "exception" and event.get("attributes"):
                return event["attributes"].get(
                    exception_attributes.EXCEPTION_STACKTRACE
                )
        return None
