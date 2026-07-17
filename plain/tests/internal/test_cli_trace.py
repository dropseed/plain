from __future__ import annotations

from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
    CODE_STACKTRACE,
)
from opentelemetry.semconv.attributes.db_attributes import DB_QUERY_TEXT

from plain.cli._trace import analyze_trace, capture_spans
from plain.test.otel import install_test_tracer

_span_exporter = install_test_tracer()


def _query_attributes(sql: str) -> dict[str, str | int]:
    return {
        DB_QUERY_TEXT: sql,
        CODE_FILE_PATH: "/app/views.py",
        CODE_LINE_NUMBER: 10,
        CODE_FUNCTION_NAME: "index",
    }


def test_groups_queries_and_flags_n_plus_one() -> None:
    _span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for _ in range(3):
            with tracer.start_as_current_span(
                "SELECT users",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes("SELECT * FROM users"),
            ):
                pass

    analysis = analyze_trace(_span_exporter.get_finished_spans())["analysis"]

    assert analysis["query_count"] == 3
    assert analysis["duplicate_query_count"] == 2
    assert len(analysis["queries"]) == 1
    assert analysis["queries"][0]["count"] == 3

    n_plus_one = [i for i in analysis["issues"] if i["type"] == "n_plus_one"]
    assert len(n_plus_one) == 1
    assert n_plus_one[0]["count"] == 3
    assert "/app/views.py:10 in index" in n_plus_one[0]["sources"]


def test_distinct_queries_are_not_flagged() -> None:
    _span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for sql in ("SELECT * FROM users", "SELECT * FROM teams"):
            with tracer.start_as_current_span(
                "query",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes(sql),
            ):
                pass

    analysis = analyze_trace(_span_exporter.get_finished_spans())["analysis"]

    assert analysis["query_count"] == 2
    assert analysis["duplicate_query_count"] == 0
    assert analysis["issues"] == []


def test_same_query_across_traces_is_not_n_plus_one() -> None:
    _span_exporter.clear()
    # --follow redirects produce one trace per hop; a query that runs once
    # per request must not be flagged as a duplicate across traces.
    tracer = trace.get_tracer("test")
    for _ in range(2):
        with tracer.start_as_current_span("GET /"):
            with tracer.start_as_current_span(
                "SELECT users",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes("SELECT * FROM users"),
            ):
                pass

    analysis = analyze_trace(_span_exporter.get_finished_spans())["analysis"]

    assert analysis["query_count"] == 2
    assert analysis["duplicate_query_count"] == 0
    assert analysis["issues"] == []


def test_n_plus_one_only_flags_app_code() -> None:
    _span_exporter.clear()
    # With app_root set, a query repeated only in framework code (e.g. a
    # preflight check under site-packages) is not flagged — only repeats in
    # project code are.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for sql, path in (
            ("SELECT framework", "/my/project/.venv/lib/site-packages/plain/pf.py"),
            ("SELECT framework", "/my/project/.venv/lib/site-packages/plain/pf.py"),
            ("SELECT framework", "/my/project/.venv/lib/site-packages/plain/pf.py"),
            ("SELECT app", "/my/project/app/views.py"),
            ("SELECT app", "/my/project/app/views.py"),
            ("SELECT app", "/my/project/app/views.py"),
        ):
            with tracer.start_as_current_span(
                "query",
                kind=trace.SpanKind.CLIENT,
                attributes={DB_QUERY_TEXT: sql, CODE_FILE_PATH: path},
            ):
                pass

    analysis = analyze_trace(
        _span_exporter.get_finished_spans(), app_root="/my/project"
    )["analysis"]

    n_plus_one = [i for i in analysis["issues"] if i["type"] == "n_plus_one"]
    assert [i["sql"] for i in n_plus_one] == ["SELECT app"]
    assert analysis["duplicate_query_count"] == 2
    assert analysis["query_count"] == 6


def test_n_plus_one_ignores_framework_repeats_of_an_app_query() -> None:
    _span_exporter.clear()
    # A query app code runs once but framework code repeats must not be
    # flagged — only the app's own per-trace repeats count toward N+1.
    app_path = "/my/project/app/views.py"
    framework_path = "/my/project/.venv/lib/site-packages/plain/pf.py"
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for path in (app_path, framework_path, framework_path, framework_path):
            with tracer.start_as_current_span(
                "query",
                kind=trace.SpanKind.CLIENT,
                attributes={DB_QUERY_TEXT: "SELECT shared", CODE_FILE_PATH: path},
            ):
                pass

    analysis = analyze_trace(
        _span_exporter.get_finished_spans(), app_root="/my/project"
    )["analysis"]

    assert [i for i in analysis["issues"] if i["type"] == "n_plus_one"] == []
    assert analysis["duplicate_query_count"] == 0
    assert analysis["query_count"] == 4


def test_emits_flat_raw_spans() -> None:
    _span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        with tracer.start_as_current_span("render template"):
            pass

    spans = analyze_trace(_span_exporter.get_finished_spans())["spans"]

    assert {s["name"] for s in spans} == {"GET /", "render template"}
    assert all(s["start_offset_ms"] >= 0 for s in spans)

    # Flat list — structure comes from parent_span_id, not nesting.
    by_name = {s["name"]: s for s in spans}
    assert by_name["GET /"]["parent_span_id"] is None
    assert by_name["render template"]["parent_span_id"] == by_name["GET /"]["span_id"]


def test_raw_span_passes_attributes_through_and_drops_stacktrace() -> None:
    _span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span(
        "query",
        kind=trace.SpanKind.CLIENT,
        attributes={
            DB_QUERY_TEXT: "SELECT 1",
            CODE_STACKTRACE: "... a huge debug stack ...",
            "custom.attr": "kept",
        },
    ):
        pass

    spans = analyze_trace(_span_exporter.get_finished_spans())["spans"]

    attributes = spans[0]["attributes"]
    assert attributes[DB_QUERY_TEXT] == "SELECT 1"
    assert attributes["custom.attr"] == "kept"
    assert CODE_STACKTRACE not in attributes


def test_capture_spans_isolates_other_processors() -> None:
    _span_exporter.clear()
    # capture_spans() detaches processors an installed package attached —
    # here, the test tracer's own exporter — so a captured span reaches
    # only the capture exporter, not the pre-existing one.
    with capture_spans() as exporter:
        with trace.get_tracer("test").start_as_current_span("inside"):
            pass

    assert "inside" in [s.name for s in exporter.get_finished_spans()]
    assert "inside" not in [s.name for s in _span_exporter.get_finished_spans()]


def test_captures_exception_issue() -> None:
    _span_exporter.clear()
    tracer = trace.get_tracer("test")
    try:
        with tracer.start_as_current_span("GET /boom"):
            raise ValueError("boom")
    except ValueError:
        pass

    result = analyze_trace(_span_exporter.get_finished_spans())

    exceptions = [i for i in result["analysis"]["issues"] if i["type"] == "exception"]
    assert len(exceptions) == 1
    assert exceptions[0]["span"] == "GET /boom"
    assert exceptions[0]["error_type"] == "ValueError"

    # The exception event also appears verbatim on the raw span.
    raw_events = result["spans"][0].get("events", [])
    assert any(e["name"] == "exception" for e in raw_events)
