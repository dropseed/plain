from datetime import UTC, datetime
from functools import cached_property

import sqlparse
from opentelemetry.semconv.attributes import db_attributes

from plain import models


@models.register_model
class Trace(models.Model):
    trace_id = models.CharField(max_length=255)
    start_time = models.DateTimeField(allow_null=True, required=False)
    end_time = models.DateTimeField(allow_null=True, required=False)

    description = models.TextField(default="", required=False)

    # Plain fields
    request_id = models.CharField(max_length=255, default="", required=False)
    session_id = models.CharField(max_length=255, default="", required=False)
    user_id = models.CharField(max_length=255, default="", required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace_id"],
                name="observe_unique_trace_id",
            )
        ]

    def __str__(self):
        return self.trace_id

    def duration_ms(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    def get_summary(self):
        """Get a concise summary string for toolbar display."""
        spans = self.spans.all()

        if not spans.exists():
            return ""

        total_spans = spans.count()
        db_queries = spans.filter(attributes__has_key="db.system").count()

        # Build summary parts
        parts = [f"{total_spans}sp"]

        if db_queries > 0:
            parts.append(f"{db_queries}db")

        # Add duration if available
        duration_ms = self.duration_ms()
        if duration_ms is not None:
            parts.append(f"{round(duration_ms, 1)}ms")

        return " ".join(parts)


@models.register_model
class Span(models.Model):
    trace = models.ForeignKey(Trace, on_delete=models.CASCADE, related_name="spans")

    span_id = models.CharField(max_length=255)

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)
    parent_id = models.CharField(max_length=255, default="", required=False)
    start_time = models.DateTimeField(allow_null=True, required=False)
    end_time = models.DateTimeField(allow_null=True, required=False)
    status = models.JSONField(default=dict)
    context = models.JSONField(default=dict)
    attributes = models.JSONField(default=dict, required=False)
    events = models.JSONField(default=list, required=False)
    links = models.JSONField(default=list, required=False)
    resource = models.JSONField(default=dict, required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace", "span_id"],
                name="observe_unique_span_id",
            )
        ]
        indexes = [
            models.Index(fields=["trace", "span_id"]),
            models.Index(fields=["trace"]),
            models.Index(fields=["start_time"]),
        ]

    def __str__(self):
        return self.span_id

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
        return self.attributes.get("db.query.text")

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
                return event["attributes"].get("exception.stacktrace")
        return None
