"""Trace capture and analysis for the `plain request` CLI command.

Captures the OpenTelemetry spans emitted while handling a request and groups
them — by statement, by trace — for human and agent inspection. Spans come
back as a flat list per trace; `request.py` turns that into the printed tree.
Internal to `request`; not public API.

This reports, it does not diagnose. Repeated statements are counted and their
call sites recorded, but nothing here decides that a repeat is an N+1 — the
reader has the trace and better judgment about the loop that produced it.

One request is one trace, so a followed redirect chain produces several. They
are analyzed separately and never merged: counting a once-per-request query
across three hops would read as a 3x repeat that no one can fix.
"""

from __future__ import annotations

from contextlib import contextmanager
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
    CODE_STACKTRACE,
)
from opentelemetry.semconv.attributes.db_attributes import (
    DB_OPERATION_NAME,
    DB_QUERY_TEXT,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.exception_attributes import (
    EXCEPTION_MESSAGE,
    EXCEPTION_STACKTRACE,
    EXCEPTION_TYPE,
)
from opentelemetry.semconv.attributes.http_attributes import HTTP_REQUEST_METHOD
from opentelemetry.semconv.attributes.url_attributes import URL_PATH, URL_QUERY

# The handler stamps this on every request span; it joins a captured trace
# back to the response the CLI reports for that hop.
_REQUEST_ID_ATTRIBUTE = "plain.request.id"

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


class QueryEntry(TypedDict):
    """One distinct SQL statement and its occurrences in this trace.

    `count` means one thing — how many times the statement ran — so it can be
    read without asking which executions it covers. Judging whether a repeat
    is a problem is left to the reader: `sources` says where each execution
    came from.
    """

    sql: str
    count: int
    total_duration_ms: float
    sources: list[str]


class TraceException(TypedDict):
    """An exception recorded on a span."""

    span: str
    error_type: str | None
    message: str | None
    stacktrace: str | None


class SpanEvent(TypedDict):
    """One OpenTelemetry span event — attributes passed through verbatim."""

    name: str
    attributes: dict[str, Any]


class RawSpan(TypedDict):
    """A captured span in generic OpenTelemetry shape — no domain projection.

    Attributes and events are passed through verbatim, minus `code.stacktrace`
    (a multi-KB debug stack the postgres instrumentation records on every
    query span). The span list is flat; `parent_span_id` gives the structure.
    The trace id belongs to the containing `CapturedTrace` rather than being
    repeated on every span.
    """

    name: str
    kind: str
    span_id: str
    parent_span_id: str | None
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
    """Derived analysis of one trace — counts, exceptions, query grouping."""

    duration_ms: float
    span_count: int
    query_count: int
    transaction_count: int
    exceptions: list[TraceException]
    queries: list[QueryEntry]


class CapturedTrace(TypedDict):
    """One captured trace — a single request — identified, read, and raw.

    `name` and `request_id` identify the hop, `analysis` is the opinionated
    read, and `spans` is the untouched OpenTelemetry shape. `request_id`
    joins a trace back to the response the CLI reports for it.
    """

    name: str
    request_id: str | None
    analysis: TraceAnalysis
    spans: list[RawSpan]


# Statements that manage a transaction rather than read or write data. They
# are counted apart from real queries: savepoint names are unique, so they
# never group, and a handful of them can fill a query list on their own.
# With plain.postgres only the savepoint three can actually appear —
# BEGIN/COMMIT are issued outside the instrumented cursor and emit no span —
# but any db instrumentation that does span them classifies the same way.
_TRANSACTION_OPERATIONS = frozenset(
    {"BEGIN", "START", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE"}
)


def _db_operation(attributes: Mapping[str, Any], sql: str) -> str:
    """The statement's leading SQL keyword, uppercased."""
    if operation := attributes.get(DB_OPERATION_NAME):
        return str(operation).upper()
    keywords = sql.lstrip("( \t\r\n").split(maxsplit=1)
    return keywords[0].upper() if keywords else ""


def _trace_name(*, root: ReadableSpan | None, spans: Sequence[ReadableSpan]) -> str:
    """Label a trace by its root span — method and path when it is a request.

    The path is what makes hops of a redirect chain tellable apart; the root
    span's own name carries the matched route, which is identical across a
    trailing-slash redirect and missing entirely when resolution failed. The
    query string is included because an auth bounce revisits one path with
    different params, and those hops have to stay distinguishable.
    """
    if root is None:
        return spans[0].name
    attributes = root.attributes or {}
    method = attributes.get(HTTP_REQUEST_METHOD)
    path = attributes.get(URL_PATH)
    if not (method and path):
        return root.name
    if query := attributes.get(URL_QUERY):
        return f"{method} {path}?{query}"
    return f"{method} {path}"


def analyze_traces(spans: Sequence[ReadableSpan]) -> list[CapturedTrace]:
    """Summarize captured OpenTelemetry spans, one entry per trace.

    Traces come back in the order they started, which for a followed redirect
    is hop order.
    """
    spans_by_trace: dict[int, list[ReadableSpan]] = {}
    for span in sorted(spans, key=lambda s: s.start_time or 0):
        spans_by_trace.setdefault(span.context.trace_id, []).append(span)

    return [_analyze_trace(trace_spans) for trace_spans in spans_by_trace.values()]


def _analyze_trace(spans: list[ReadableSpan]) -> CapturedTrace:
    """Analyze one trace's spans, which arrive ordered by start time."""
    queries_by_sql: dict[str, QueryEntry] = {}
    transaction_count = 0
    exceptions: list[TraceException] = []

    for span in spans:
        attributes = span.attributes or {}

        if (raw_sql := attributes.get(DB_QUERY_TEXT)) is not None:
            sql = str(raw_sql)
            if _db_operation(attributes, sql) in _TRANSACTION_OPERATIONS:
                transaction_count += 1
            else:
                entry = queries_by_sql.setdefault(
                    sql,
                    {"sql": sql, "count": 0, "total_duration_ms": 0.0, "sources": []},
                )
                entry["count"] += 1
                entry["total_duration_ms"] += _span_duration_ms(span)
                if (location := _source_location(attributes)) and (
                    location not in entry["sources"]
                ):
                    entry["sources"].append(location)

        for event in span.events:
            if event.name == "exception":
                event_attributes = event.attributes or {}
                exceptions.append(
                    {
                        "span": span.name,
                        "error_type": _text(
                            event_attributes.get(EXCEPTION_TYPE)
                            or attributes.get(ERROR_TYPE)
                        ),
                        "message": _text(event_attributes.get(EXCEPTION_MESSAGE)),
                        "stacktrace": _text(event_attributes.get(EXCEPTION_STACKTRACE)),
                    }
                )

    # Slowest first — the list answers "where did the time go", and a repeat
    # count is visible on its own row for anyone asking the other question.
    queries = sorted(
        queries_by_sql.values(),
        key=lambda q: (-q["total_duration_ms"], -q["count"]),
    )
    query_count = sum(query["count"] for query in queries)
    for query in queries:
        query["total_duration_ms"] = round(query["total_duration_ms"], 2)

    # Trace wall-clock duration: first span start to last span end. Spans
    # arrive sorted by start time, so the earliest is spans[0]; end times can
    # still be out of order, so those do need a scan.
    trace_start = spans[0].start_time
    trace_end = max((s.end_time for s in spans if s.end_time is not None), default=None)
    if trace_start is not None and trace_end is not None:
        duration_ms = round((trace_end - trace_start) / 1_000_000, 2)
    else:
        duration_ms = 0.0

    # The trace's entry span — the one nothing else in the trace started.
    root = next((span for span in spans if span.parent is None), None)
    request_id = (root.attributes or {}).get(_REQUEST_ID_ATTRIBUTE) if root else None

    return {
        "name": _trace_name(root=root, spans=spans),
        "request_id": _text(request_id),
        "analysis": {
            "duration_ms": duration_ms,
            "span_count": len(spans),
            "query_count": query_count,
            "transaction_count": transaction_count,
            "exceptions": exceptions,
            "queries": queries,
        },
        "spans": [_span_dict(s, trace_start) for s in spans],
    }


def capture_available() -> bool:
    """Whether `capture_spans` can run.

    Needs the OpenTelemetry SDK importable (it ships with `plain.connect`
    and `plain.pytest`) and a global tracer provider `capture_spans` knows
    how to mutate — the SDK's own, or the proxy it can replace. A
    third-party provider is left alone rather than crashed into.
    """
    if find_spec("opentelemetry.sdk") is None:
        return False
    from opentelemetry.sdk.trace import TracerProvider

    provider = trace.get_tracer_provider()
    return isinstance(provider, TracerProvider | trace.ProxyTracerProvider)


@contextmanager
def capture_spans() -> Generator[InMemorySpanExporter]:
    """Capture every span emitted within the block, in isolation.

    For the duration of the block the active tracer provider records every
    span (its sampler is forced on) and delivers spans *only* to an in-memory
    exporter. Span processors an installed package configured —
    `plain.connect`'s OTLP exporter — are detached, so a captured request
    is neither persisted nor shipped anywhere. The sampler and processors
    are restored on exit.

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
        # plain.connect installs a provider during app startup, before any
        # CLI command runs.
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
