from __future__ import annotations

import json
import secrets
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

import sqlparse
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.semconv._incubating.attributes import (
    exception_attributes,
    session_attributes,
    user_attributes,
)
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_NAMESPACE,
)
from opentelemetry.semconv._incubating.attributes.db_attributes import (
    DB_QUERY_PARAMETER_TEMPLATE,
)
from opentelemetry.semconv.attributes import db_attributes, service_attributes
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_COLUMN_NUMBER,
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
    CODE_STACKTRACE,
)
from opentelemetry.trace import format_trace_id

from plain import models
from plain.runtime import settings
from plain.urls import reverse
from plain.utils import timezone


@models.register_model
class Trace(models.Model):
    trace_id = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    root_span_name = models.TextField(default="", required=False)
    summary = models.CharField(max_length=255, default="", required=False)

    # Plain fields
    request_id = models.CharField(max_length=255, default="", required=False)
    session_id = models.CharField(max_length=255, default="", required=False)
    user_id = models.CharField(max_length=255, default="", required=False)
    app_name = models.CharField(max_length=255, default="", required=False)
    app_version = models.CharField(max_length=255, default="", required=False)

    # Shareable URL fields
    share_id = models.CharField(max_length=32, default="", required=False)
    share_created_at = models.DateTimeField(allow_null=True, required=False)

    if TYPE_CHECKING:
        from plain.models.fields.related_managers import BaseRelatedManager

        spans: BaseRelatedManager
        logs: BaseRelatedManager

    model_options = models.Options(
        ordering=["-start_time"],
        constraints=[
            models.UniqueConstraint(
                fields=["trace_id"],
                name="observer_unique_trace_id",
            )
        ],
        indexes=[
            models.Index(fields=["trace_id"]),
            models.Index(fields=["start_time"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["share_id"]),
            models.Index(fields=["session_id"]),
        ],
    )

    def __str__(self) -> str:
        return self.trace_id

    def get_absolute_url(self) -> str:
        """Return the canonical URL for this trace."""
        return reverse("observer:trace_detail", trace_id=self.trace_id)

    def generate_share_id(self) -> str:
        """Generate a unique share ID for this trace."""
        self.share_id = secrets.token_urlsafe(24)
        self.share_created_at = timezone.now()
        self.save(update_fields=["share_id", "share_created_at"])
        return self.share_id

    def remove_share_id(self) -> None:
        """Remove the share ID from this trace."""
        self.share_id = ""
        self.share_created_at = None
        self.save(update_fields=["share_id", "share_created_at"])

    def duration_ms(self) -> float:
        return (self.end_time - self.start_time).total_seconds() * 1000

    def get_trace_summary(self, spans: Iterable[Span]) -> str:
        # Count database queries with query text and track duplicates
        query_texts: list[str] = []
        for span in spans:
            if query_text := span.attributes.get(db_attributes.DB_QUERY_TEXT):
                query_texts.append(query_text)

        query_counts = Counter(query_texts)
        query_total = len(query_texts)
        duplicate_count = sum(query_counts.values()) - len(query_counts)

        # Build summary: "n spans, n queries (n duplicates), Xms"
        parts: list[str] = []

        # Queries count with duplicates
        if query_total > 0:
            query_part = f"{query_total} quer{'y' if query_total == 1 else 'ies'}"
            if duplicate_count > 0:
                query_part += f" ({duplicate_count} duplicate{'' if duplicate_count == 1 else 's'})"
            parts.append(query_part)

        # Duration
        if (duration_ms := self.duration_ms()) is not None:
            parts.append(f"{round(duration_ms, 1)}ms")

        return " • ".join(parts)

    @classmethod
    def from_opentelemetry_spans(cls, spans: Sequence[ReadableSpan]) -> Trace:
        """Create a Trace instance from a list of OpenTelemetry spans."""
        # Get trace information from the first span
        first_span = spans[0]
        trace_id = f"0x{format_trace_id(first_span.get_span_context().trace_id)}"

        # Find trace boundaries and root span info
        earliest_start = None
        latest_end = None
        root_span = None
        request_id = ""
        user_id = ""
        session_id = ""
        app_name = ""
        app_version = ""

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

            # Access Resource attributes if not found in span attributes
            if resource := getattr(span, "resource", None):
                app_name = app_name or resource.attributes.get(
                    service_attributes.SERVICE_NAME, ""
                )
                app_version = app_version or resource.attributes.get(
                    service_attributes.SERVICE_VERSION, ""
                )

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

        return cls(
            trace_id=trace_id,
            start_time=start_time,
            end_time=end_time
            or start_time,  # Use start_time as fallback for active traces
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            app_name=app_name or settings.NAME,
            app_version=app_version or settings.VERSION,
            root_span_name=root_span.name if root_span else "",
        )

    def as_dict(self) -> dict[str, Any]:
        spans = [
            span.span_data for span in self.spans.query.all().order_by("start_time")
        ]
        logs = [
            {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "message": log.message,
                "span_id": log.span_id,
            }
            for log in self.logs.query.all().order_by("timestamp")
        ]

        return {
            "trace_id": self.trace_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms(),
            "summary": self.summary,
            "root_span_name": self.root_span_name,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "spans": spans,
            "logs": logs,
        }

    def get_timeline_events(self) -> list[dict[str, Any]]:
        """Get chronological list of spans and logs for unified timeline display."""
        events: list[dict[str, Any]] = []

        for span in self.spans.query.all().annotate_spans():
            events.append(
                {
                    "type": "span",
                    "timestamp": span.start_time,
                    "instance": span,
                    "span_level": span.level,
                }
            )

            # Add logs for this span
            for log in self.logs.query.filter(span=span):
                events.append(
                    {
                        "type": "log",
                        "timestamp": log.timestamp,
                        "instance": log,
                        "span_level": span.level + 1,
                    }
                )

        # Add unlinked logs (logs without span)
        for log in self.logs.query.filter(span__isnull=True):
            events.append(
                {
                    "type": "log",
                    "timestamp": log.timestamp,
                    "instance": log,
                    "span_level": 0,
                }
            )

        # Sort by timestamp
        return sorted(events, key=lambda x: x["timestamp"])


class SpanQuerySet(models.QuerySet["Span"]):
    def annotate_spans(self) -> list[Span]:
        """Annotate spans with nesting levels and duplicate query warnings."""
        spans: list[Span] = list(self.order_by("start_time"))

        # Build span dictionary for parent lookups
        span_dict: dict[str, Span] = {span.span_id: span for span in spans}

        # Calculate nesting levels
        for span in spans:
            if not span.parent_id:
                span.level = 0
            else:
                # Find parent's level and add 1
                parent = span_dict.get(span.parent_id)
                parent_level = parent.level if parent else 0
                span.level = parent_level + 1

        query_counts: dict[str, int] = {}

        # First pass: count queries
        for span in spans:
            if sql_query := span.sql_query:
                query_counts[sql_query] = query_counts.get(sql_query, 0) + 1

        # Second pass: add annotations
        query_occurrences: dict[str, int] = {}
        for span in spans:
            span.annotations = []

            # Check for duplicate queries
            if sql_query := span.sql_query:
                count = query_counts[sql_query]
                if count > 1:
                    occurrence = query_occurrences.get(sql_query, 0) + 1
                    query_occurrences[sql_query] = occurrence

                    span.annotations.append(
                        {
                            "message": f"Duplicate query ({occurrence} of {count})",
                            "severity": "warning",
                        }
                    )

        return spans


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

    query = SpanQuerySet()

    model_options = models.Options(
        ordering=["-start_time"],
        constraints=[
            models.UniqueConstraint(
                fields=["trace", "span_id"],
                name="observer_unique_span_id",
            )
        ],
        indexes=[
            models.Index(fields=["span_id"]),
            models.Index(fields=["trace", "span_id"]),
            models.Index(fields=["trace"]),
            models.Index(fields=["start_time"]),
        ],
    )

    if TYPE_CHECKING:
        level: int
        annotations: list[dict[str, Any]]

    @classmethod
    def from_opentelemetry_span(cls, otel_span: ReadableSpan, trace: Trace) -> Span:
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

    def __str__(self) -> str:
        return self.span_id

    @property
    def attributes(self) -> Mapping[str, Any]:
        """Get attributes from span_data."""
        return cast(Mapping[str, Any], self.span_data.get("attributes", {}))

    @property
    def events(self) -> list[Mapping[str, Any]]:
        """Get events from span_data."""
        return cast(list[Mapping[str, Any]], self.span_data.get("events", []))

    @property
    def links(self) -> list[Mapping[str, Any]]:
        """Get links from span_data."""
        return cast(list[Mapping[str, Any]], self.span_data.get("links", []))

    @property
    def resource(self) -> Mapping[str, Any]:
        """Get resource from span_data."""
        return cast(Mapping[str, Any], self.span_data.get("resource", {}))

    @property
    def context(self) -> Mapping[str, Any]:
        """Get context from span_data."""
        return cast(Mapping[str, Any], self.span_data.get("context", {}))

    def duration_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0

    @cached_property
    def sql_query(self) -> str | None:
        """Get the SQL query if this span contains one."""
        return self.attributes.get(db_attributes.DB_QUERY_TEXT)

    @cached_property
    def sql_query_params(self) -> dict[str, Any]:
        """Get query parameters from attributes that start with 'db.query.parameter.'"""
        if not self.attributes:
            return {}

        query_params: dict[str, Any] = {}
        for key, value in self.attributes.items():
            if key.startswith(DB_QUERY_PARAMETER_TEMPLATE + "."):
                param_name = key.replace(DB_QUERY_PARAMETER_TEMPLATE + ".", "")
                query_params[param_name] = value

        return query_params

    @cached_property
    def source_code_location(self) -> dict[str, Any] | None:
        """Get the source code location attributes from this span."""
        if not self.attributes:
            return None

        # Look for common semantic convention code attributes
        code_attrs = {}
        code_attribute_mappings = {
            CODE_FILE_PATH: "File",
            CODE_LINE_NUMBER: "Line",
            CODE_FUNCTION_NAME: "Function",
            CODE_NAMESPACE: "Namespace",
            CODE_COLUMN_NUMBER: "Column",
            CODE_STACKTRACE: "Stacktrace",
        }

        for attr_key, display_name in code_attribute_mappings.items():
            if attr_key in self.attributes:
                code_attrs[display_name] = self.attributes[attr_key]

        return code_attrs if code_attrs else None

    def get_formatted_sql(self) -> str | None:
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

    def format_event_timestamp(
        self, timestamp: float | int | datetime | str
    ) -> datetime | str:
        """Convert event timestamp to a readable datetime."""
        if isinstance(timestamp, int | float):
            ts_value = float(timestamp)
            try:
                # Try as seconds first
                if ts_value > 1e10:  # Likely nanoseconds
                    ts_value /= 1e9
                elif ts_value > 1e7:  # Likely milliseconds
                    ts_value /= 1e3

                return datetime.fromtimestamp(ts_value, tz=UTC)
            except (ValueError, OSError):
                return str(ts_value)
        if isinstance(timestamp, datetime):
            return timestamp
        return str(timestamp)

    def get_exception_stacktrace(self) -> str | None:
        """Get the exception stacktrace if this span has an exception event."""
        if not self.events:
            return None

        for event in self.events:
            if event.get("name") == "exception" and event.get("attributes"):
                return event["attributes"].get(
                    exception_attributes.EXCEPTION_STACKTRACE
                )
        return None


@models.register_model
class Log(models.Model):
    trace = models.ForeignKey(Trace, on_delete=models.CASCADE, related_name="logs")
    span = models.ForeignKey(
        Span,
        on_delete=models.SET_NULL,
        allow_null=True,
        required=False,
        related_name="logs",
    )

    timestamp = models.DateTimeField()
    level = models.CharField(max_length=20)
    message = models.TextField()

    model_options = models.Options(
        ordering=["timestamp"],
        indexes=[
            models.Index(fields=["trace", "timestamp"]),
            models.Index(fields=["trace", "span"]),
            models.Index(fields=["timestamp"]),
            models.Index(fields=["trace"]),
        ],
    )
