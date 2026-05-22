"""Trace capture and analysis for the `plain request` CLI command.

Captures the OpenTelemetry spans emitted while handling a single request and
summarizes them — query grouping, N+1/exception detection, a span tree — for
human and agent inspection. Internal to the `request` command; not public API.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
    CODE_STACKTRACE,
)
from opentelemetry.semconv.attributes.db_attributes import DB_QUERY_TEXT
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.exception_attributes import (
    EXCEPTION_MESSAGE,
    EXCEPTION_STACKTRACE,
    EXCEPTION_TYPE,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )


def _span_duration_ms(span: ReadableSpan) -> float:
    if span.start_time is None or span.end_time is None:
        return 0.0
    return (span.end_time - span.start_time) / 1_000_000


def _span_start_offset_ms(span: ReadableSpan, trace_start: int | None) -> float:
    """Milliseconds from the trace's first span to this span's start."""
    if span.start_time is None or trace_start is None:
        return 0.0
    return (span.start_time - trace_start) / 1_000_000


def _source_location(attributes: Mapping[str, Any]) -> str | None:
    """Build a human-readable source location from OTel code.* attributes."""
    file_path = attributes.get(CODE_FILE_PATH)
    if not file_path:
        return None
    location = str(file_path)
    if line := attributes.get(CODE_LINE_NUMBER):
        location += f":{line}"
    if function := attributes.get(CODE_FUNCTION_NAME):
        location += f" in {function}"
    return location


def _text(value: Any) -> str | None:
    """Coerce an OpenTelemetry attribute value to text, preserving None."""
    return None if value is None else str(value)


def _is_app_path(path: str, app_root: str) -> bool:
    """Whether a source path belongs to the project, not an installed dependency."""
    return path.startswith(app_root + os.sep) and "site-packages" not in path


class QueryEntry(TypedDict):
    """One distinct SQL statement and its aggregated occurrences."""

    sql: str
    count: int
    total_duration_ms: float
    sources: list[str]


class NPlusOneIssue(TypedDict):
    """A query repeated within a single trace — a likely N+1."""

    type: Literal["n_plus_one"]
    description: str
    sql: str
    count: int
    total_duration_ms: float
    sources: list[str]


class ExceptionIssue(TypedDict):
    """An exception recorded on a span."""

    type: Literal["exception"]
    description: str
    span: str
    error_type: str | None
    message: str | None
    stacktrace: str | None


type Issue = NPlusOneIssue | ExceptionIssue


class SpanEvent(TypedDict):
    """One OpenTelemetry span event — attributes passed through verbatim."""

    name: str
    attributes: dict[str, Any]


class RawSpan(TypedDict):
    """A captured span in generic OpenTelemetry shape — no domain projection.

    Attributes and events are passed through verbatim, minus `code.stacktrace`
    (a multi-KB debug stack the postgres instrumentation records on every
    query span). The span list is flat; `parent_span_id` gives the structure.
    """

    name: str
    kind: str
    span_id: str
    parent_span_id: str | None
    trace_id: str
    start_offset_ms: float
    duration_ms: float
    status: NotRequired[str]
    attributes: NotRequired[dict[str, Any]]
    events: NotRequired[list[SpanEvent]]


# `code.stacktrace` is a full, multi-KB filtered stack the postgres
# instrumentation records on every query span in DEBUG. It would dwarf the
# rest of the trace, so it is dropped from the raw span output.
_EXCLUDED_SPAN_ATTRIBUTES = frozenset({CODE_STACKTRACE})


def _span_dict(span: ReadableSpan, trace_start: int | None) -> RawSpan:
    """Convert a captured span to a generic, JSON-serializable OTel dict."""
    raw: RawSpan = {
        "name": span.name,
        "kind": span.kind.name,
        "span_id": trace.format_span_id(span.context.span_id),
        "parent_span_id": (
            trace.format_span_id(span.parent.span_id)
            if span.parent is not None
            else None
        ),
        "trace_id": trace.format_trace_id(span.context.trace_id),
        "start_offset_ms": round(_span_start_offset_ms(span, trace_start), 2),
        "duration_ms": round(_span_duration_ms(span), 2),
    }
    status = span.status.status_code.name
    if status != "UNSET":
        raw["status"] = status
    attributes = {
        key: value
        for key, value in (span.attributes or {}).items()
        if key not in _EXCLUDED_SPAN_ATTRIBUTES
    }
    if attributes:
        raw["attributes"] = attributes
    events: list[SpanEvent] = [
        {"name": event.name, "attributes": dict(event.attributes or {})}
        for event in span.events
    ]
    if events:
        raw["events"] = events
    return raw


class TraceAnalysis(TypedDict):
    """Derived analysis of a captured trace — counts, issues, query grouping."""

    duration_ms: float
    span_count: int
    query_count: int
    duplicate_query_count: int
    issues: list[Issue]
    queries: list[QueryEntry]


class TraceResult(TypedDict):
    """The `analyze_trace` result: derived `analysis` plus the raw `spans`.

    `analysis` is everything computed; `spans` is the raw captured trace in
    generic OpenTelemetry shape. The split keeps the opinionated read and the
    untouched source data cleanly separated.
    """

    analysis: TraceAnalysis
    spans: list[RawSpan]


def analyze_trace(
    spans: Sequence[ReadableSpan], *, app_root: str | None = None
) -> TraceResult:
    """Summarize captured OpenTelemetry spans for human and agent inspection.

    Returns a JSON-serializable `TraceResult`: derived `analysis` (query
    grouping, N+1/exception issues, counts) and `spans` — the raw captured
    trace in generic OpenTelemetry shape, a flat list ordered by start time.

    When `app_root` is given, N+1 flagging is limited to queries originating
    in project code — framework-internal repeats are not flagged.
    """
    queries_by_sql: dict[str, QueryEntry] = {}
    # Per-trace occurrence counts, keyed (trace_id, sql). N+1 detection must
    # stay within a single trace — otherwise --follow redirects (one trace
    # per hop) inflate once-per-request queries into false duplicates.
    counts_by_trace: dict[tuple[int, str], int] = {}
    # The same per-trace counts, restricted to occurrences whose call site is
    # project code. When app_root is given, N+1 detection counts only these,
    # so a query the framework repeats (preflight, the toolbar) is not flagged
    # just because app code happened to run it once too.
    app_counts_by_trace: dict[tuple[int, str], int] = {}
    issues: list[Issue] = []

    for span in spans:
        attributes = span.attributes or {}

        if (raw_sql := attributes.get(DB_QUERY_TEXT)) is not None:
            sql = str(raw_sql)
            trace_key = (span.context.trace_id, sql)
            counts_by_trace[trace_key] = counts_by_trace.get(trace_key, 0) + 1
            entry: QueryEntry | None = queries_by_sql.get(sql)
            if entry is None:
                entry = {
                    "sql": sql,
                    "count": 0,
                    "total_duration_ms": 0.0,
                    "sources": [],
                }
                queries_by_sql[sql] = entry
            entry["count"] += 1
            entry["total_duration_ms"] += _span_duration_ms(span)
            source = _source_location(attributes)
            if source and source not in entry["sources"]:
                entry["sources"].append(source)
            if app_root is not None:
                file_path = attributes.get(CODE_FILE_PATH)
                if file_path and _is_app_path(str(file_path), app_root):
                    app_counts_by_trace[trace_key] = (
                        app_counts_by_trace.get(trace_key, 0) + 1
                    )

        for event in span.events:
            if event.name == "exception":
                event_attributes = event.attributes or {}
                exception_issue: ExceptionIssue = {
                    "type": "exception",
                    "description": f"Exception in {span.name}",
                    "span": span.name,
                    "error_type": _text(
                        event_attributes.get(EXCEPTION_TYPE)
                        or attributes.get(ERROR_TYPE)
                    ),
                    "message": _text(event_attributes.get(EXCEPTION_MESSAGE)),
                    "stacktrace": _text(event_attributes.get(EXCEPTION_STACKTRACE)),
                }
                issues.append(exception_issue)

    # Counts that drive N+1 detection: app-originated occurrences when scoped
    # to a project, every occurrence otherwise.
    detection_counts = counts_by_trace if app_root is None else app_counts_by_trace

    # Highest single-trace occurrence count per query — the N+1 signal.
    max_in_trace: dict[str, int] = {}
    duplicate_query_count = 0
    for (_trace_id, sql), count in detection_counts.items():
        max_in_trace[sql] = max(max_in_trace.get(sql, 0), count)
        if count > 1:
            duplicate_query_count += count - 1

    queries: list[QueryEntry] = []
    query_count = 0

    for query in sorted(
        queries_by_sql.values(),
        key=lambda q: (-q["count"], -q["total_duration_ms"]),
    ):
        query["total_duration_ms"] = round(query["total_duration_ms"], 2)
        query_count += query["count"]
        repeated = max_in_trace.get(query["sql"], 0)
        if repeated > 1:
            n_plus_one: NPlusOneIssue = {
                "type": "n_plus_one",
                "description": f"Query executed {repeated} times — likely N+1",
                "sql": query["sql"],
                "count": repeated,
                "total_duration_ms": query["total_duration_ms"],
                "sources": query["sources"],
            }
            issues.insert(0, n_plus_one)
        queries.append(query)

    # Trace wall-clock duration: first span start to last span end.
    start_times = [s.start_time for s in spans if s.start_time is not None]
    end_times = [s.end_time for s in spans if s.end_time is not None]
    trace_start = min(start_times) if start_times else None
    trace_end = max(end_times) if end_times else None
    if trace_start is not None and trace_end is not None:
        duration_ms = round((trace_end - trace_start) / 1_000_000, 2)
    else:
        duration_ms = 0.0

    ordered_spans = sorted(spans, key=lambda s: s.start_time or 0)

    return {
        "analysis": {
            "duration_ms": duration_ms,
            "span_count": len(spans),
            "query_count": query_count,
            "duplicate_query_count": duplicate_query_count,
            "issues": issues,
            "queries": queries,
        },
        "spans": [_span_dict(s, trace_start) for s in ordered_spans],
    }


def capture_available() -> bool:
    """Whether `capture_spans` can run — the OpenTelemetry SDK must be installed.

    The SDK is not a Plain core dependency; it ships with `plain.observer`,
    `plain.connect`, and `plain.pytest`.
    """
    return find_spec("opentelemetry.sdk") is not None


@contextmanager
def capture_spans() -> Generator[InMemorySpanExporter]:
    """Capture every span emitted within the block, in isolation.

    For the duration of the block the active tracer provider records every
    span (its sampler is forced on) and delivers spans *only* to an in-memory
    exporter. Span processors an installed package configured —
    `plain.observer`'s database writer, `plain.connect`'s OTLP exporter — are
    detached, so a captured request is neither persisted nor shipped anywhere.
    The sampler and processors are restored on exit.

    Requires the OpenTelemetry SDK — guard calls with `capture_available()`.
    For one-shot, single-threaded callers such as CLI commands; it mutates
    process-global tracing state.
    """
    # The SDK is not a Plain core dependency, so import it lazily — this
    # module must stay importable on the CLI path without it.
    from opentelemetry.sdk.trace import (
        SynchronousMultiSpanProcessor,
        TracerProvider,
        sampling,
    )
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()

    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        # Nothing configured a provider — install a bare one so the still
        # unresolved proxy tracers bind to it. `set_tracer_provider` is
        # one-shot, so this provider stays for the life of the process, but
        # the `finally` below strips its processors, leaving it inert. This
        # branch is only reached when no OTel package is installed at all:
        # plain.connect and plain.observer both install a provider during
        # app startup, before any CLI command runs.
        trace.set_tracer_provider(TracerProvider())

    # From here a real provider exists either way — capture by mutating it.
    provider = cast(TracerProvider, trace.get_tracer_provider())

    # Instrumentation tracers baked in this provider's sampler and its
    # composite span processor by reference, so isolate by mutating those
    # objects in place: force the sampler to record every span, and swap the
    # composite's processor list for one holding only our exporter.
    sampler = provider.sampler
    composite = cast(SynchronousMultiSpanProcessor, provider._active_span_processor)

    had_sampler_attr = "should_sample" in sampler.__dict__
    original_should_sample = sampler.should_sample
    original_processors = composite._span_processors

    sampler.should_sample = sampling.ALWAYS_ON.should_sample  # ty: ignore[invalid-assignment]
    composite._span_processors = (SimpleSpanProcessor(exporter),)
    try:
        yield exporter
    finally:
        composite._span_processors = original_processors
        if had_sampler_attr:
            sampler.should_sample = original_should_sample  # ty: ignore[invalid-assignment]
        else:
            del sampler.should_sample
