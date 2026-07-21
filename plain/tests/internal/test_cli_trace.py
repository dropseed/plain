from __future__ import annotations

import pytest
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
from opentelemetry.semconv.attributes.http_attributes import HTTP_REQUEST_METHOD
from opentelemetry.semconv.attributes.url_attributes import URL_PATH

from plain.cli._trace import (
    CapturedTrace,
    RawSpan,
    TraceAnalysis,
    analyze_traces,
    capture_available,
    capture_spans,
)
from plain.cli.request import (
    _TRACE_EMPTY,
    _TRACE_NOT_REACHED,
    _TRACE_UNAVAILABLE,
    _render_span_tree,
    _render_traces,
    _trace_note,
)
from plain.test.otel import install_test_tracer

_span_exporter = install_test_tracer()


@pytest.fixture
def _otel_clean() -> None:
    _span_exporter.clear()


def _query_attributes(sql: str) -> dict[str, str | int]:
    return {
        DB_QUERY_TEXT: sql,
        CODE_FILE_PATH: "/app/views.py",
        CODE_LINE_NUMBER: 10,
        CODE_FUNCTION_NAME: "index",
    }


def _only_analysis() -> TraceAnalysis:
    """The analysis of the single trace the test emitted."""
    traces = analyze_traces(_span_exporter.get_finished_spans())
    assert len(traces) == 1
    return traces[0]["analysis"]


@pytest.mark.usefixtures("_otel_clean")
def test_groups_repeated_statements_with_their_call_site() -> None:
    # Repeats are reported, not diagnosed: one entry carrying the count and
    # where it ran, for the reader to judge.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for _ in range(3):
            with tracer.start_as_current_span(
                "SELECT users",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes("SELECT * FROM users"),
            ):
                pass

    analysis = _only_analysis()

    assert analysis["query_count"] == 3
    assert len(analysis["queries"]) == 1
    assert analysis["queries"][0]["count"] == 3
    assert analysis["queries"][0]["sources"] == ["/app/views.py:10 in index"]


@pytest.mark.usefixtures("_otel_clean")
def test_distinct_statements_stay_separate_entries() -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for sql in ("SELECT * FROM users", "SELECT * FROM teams"):
            with tracer.start_as_current_span(
                "query",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes(sql),
            ):
                pass

    analysis = _only_analysis()

    assert analysis["query_count"] == 2
    assert [q["count"] for q in analysis["queries"]] == [1, 1]


@pytest.mark.usefixtures("_otel_clean")
def test_each_redirect_hop_is_analyzed_on_its_own() -> None:
    # --follow redirects produce one trace per hop. A query that runs once per
    # request must stay a 1x query in each hop's analysis rather than merging
    # into a 2x count that reads as a repeat nobody can fix.
    tracer = trace.get_tracer("test")
    for path in ("/old", "/new"):
        with tracer.start_as_current_span(
            "GET",
            kind=trace.SpanKind.SERVER,
            attributes={HTTP_REQUEST_METHOD: "GET", URL_PATH: path},
        ):
            with tracer.start_as_current_span(
                "SELECT users",
                kind=trace.SpanKind.CLIENT,
                attributes=_query_attributes("SELECT * FROM users"),
            ):
                pass

    traces = analyze_traces(_span_exporter.get_finished_spans())

    # Named by method and path, so the hops are tellable apart even though
    # both root spans are called "GET".
    assert [t["name"] for t in traces] == ["GET /old", "GET /new"]
    for captured in traces:
        assert captured["analysis"]["query_count"] == 1


@pytest.mark.usefixtures("_otel_clean")
def test_query_sources_dedup_distinct_call_sites() -> None:
    # Each distinct call site is recorded once, as its raw location string —
    # the path is the information, so no classification travels with it.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for path in (
            "/my/project/app/views.py",
            "/my/project/.venv/lib/site-packages/plain/sessions/core.py",
        ):
            with tracer.start_as_current_span(
                "query",
                kind=trace.SpanKind.CLIENT,
                attributes={DB_QUERY_TEXT: "SELECT shared", CODE_FILE_PATH: path},
            ):
                pass

    analysis = _only_analysis()

    assert analysis["queries"][0]["sources"] == [
        "/my/project/app/views.py",
        "/my/project/.venv/lib/site-packages/plain/sessions/core.py",
    ]


@pytest.mark.usefixtures("_otel_clean")
def test_transaction_statements_are_counted_apart_from_queries() -> None:
    # Savepoint names are unique, so they never group and would otherwise fill
    # the query list on their own while telling you nothing to fix.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        for sql, operation in (
            ("SELECT * FROM users", "SELECT"),
            ('SAVEPOINT "s1"', "SAVEPOINT"),
            ('RELEASE SAVEPOINT "s1"', "RELEASE"),
            # No db.operation.name attribute — falls back to the SQL keyword.
            ("COMMIT", None),
        ):
            attributes: dict[str, str] = {DB_QUERY_TEXT: sql}
            if operation:
                attributes[DB_OPERATION_NAME] = operation
            with tracer.start_as_current_span(
                "query", kind=trace.SpanKind.CLIENT, attributes=attributes
            ):
                pass

    analysis = _only_analysis()

    assert analysis["query_count"] == 1
    assert analysis["transaction_count"] == 3
    assert [q["sql"] for q in analysis["queries"]] == ["SELECT * FROM users"]


@pytest.mark.usefixtures("_otel_clean")
def test_emits_flat_raw_spans() -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("GET /"):
        with tracer.start_as_current_span("render template"):
            pass

    spans = analyze_traces(_span_exporter.get_finished_spans())[0]["spans"]

    assert {s["name"] for s in spans} == {"GET /", "render template"}
    assert all(s["start_offset_ms"] >= 0 for s in spans)

    # Flat list — structure comes from parent_span_id, not nesting.
    by_name = {s["name"]: s for s in spans}
    assert by_name["GET /"]["parent_span_id"] is None
    assert by_name["render template"]["parent_span_id"] == by_name["GET /"]["span_id"]


@pytest.mark.usefixtures("_otel_clean")
def test_raw_span_passes_attributes_through_and_drops_stacktrace() -> None:
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

    spans = analyze_traces(_span_exporter.get_finished_spans())[0]["spans"]

    attributes = spans[0]["attributes"]
    assert attributes[DB_QUERY_TEXT] == "SELECT 1"
    assert attributes["custom.attr"] == "kept"
    assert CODE_STACKTRACE not in attributes


@pytest.mark.usefixtures("_otel_clean")
def test_capture_spans_isolates_other_processors() -> None:
    # capture_spans() detaches processors an installed package attached —
    # here, the test tracer's own exporter — so a captured span reaches
    # only the capture exporter, not the pre-existing one.
    with capture_spans() as exporter:
        with trace.get_tracer("test").start_as_current_span("inside"):
            pass

    assert "inside" in [s.name for s in exporter.get_finished_spans()]
    assert "inside" not in [s.name for s in _span_exporter.get_finished_spans()]


@pytest.mark.usefixtures("_otel_clean")
def test_captures_exceptions() -> None:
    tracer = trace.get_tracer("test")
    try:
        with tracer.start_as_current_span("GET /boom"):
            raise ValueError("boom")
    except ValueError:
        pass

    captured = analyze_traces(_span_exporter.get_finished_spans())[0]

    exceptions = captured["analysis"]["exceptions"]
    assert len(exceptions) == 1
    assert exceptions[0]["span"] == "GET /boom"
    assert exceptions[0]["error_type"] == "ValueError"
    assert exceptions[0]["message"] == "boom"

    # The exception event also appears verbatim on the raw span.
    raw_events = captured["spans"][0].get("events", [])
    assert any(e["name"] == "exception" for e in raw_events)


def _raw_span(*, span_id: str, parent: str | None, name: str) -> RawSpan:
    return {
        "name": name,
        "kind": "INTERNAL",
        "span_id": span_id,
        "parent_span_id": parent,
        "start_offset_ms": 0.0,
        "duration_ms": 1.0,
    }


def test_span_tree_nests_children_under_their_parent(capsys) -> None:
    _render_span_tree(
        [
            _raw_span(span_id="a1", parent=None, name="GET /admin"),
            _raw_span(span_id="a2", parent="a1", name="render admin.html"),
            _raw_span(span_id="a3", parent="a2", name="SELECT users"),
        ]
    )

    # Parents before children, two spaces deeper per level.
    assert capsys.readouterr().out.splitlines() == [
        "        1.00ms  GET /admin  INTERNAL",
        "        1.00ms    render admin.html  INTERNAL",
        "        1.00ms      SELECT users  INTERNAL",
    ]


def test_span_tree_keeps_spans_whose_parent_was_not_captured(capsys) -> None:
    # An uncaptured parent can't be nested under anything, so the orphan
    # becomes a root rather than disappearing from the tree.
    _render_span_tree(
        [_raw_span(span_id="child", parent="missing-parent", name="orphaned work")]
    )

    assert capsys.readouterr().out.splitlines() == [
        "        1.00ms  orphaned work  INTERNAL"
    ]


def test_span_tree_survives_a_span_that_parents_itself(capsys) -> None:
    # Malformed instrumentation must not hang the command or silently drop
    # spans the reported count already promised.
    _render_span_tree(
        [
            _raw_span(span_id="a1", parent=None, name="GET /"),
            _raw_span(span_id="a2", parent="a2", name="self parented"),
        ]
    )

    assert capsys.readouterr().out.splitlines() == [
        "        1.00ms  GET /  INTERNAL",
        "        1.00ms  self parented  INTERNAL",
    ]


def test_span_tree_survives_two_spans_sharing_an_id(capsys) -> None:
    # A duplicate id used to recurse until RecursionError. Both spans are
    # still shown — the count printed above the tree promises them.
    _render_span_tree(
        [
            _raw_span(span_id="x", parent=None, name="root"),
            _raw_span(span_id="x", parent="x", name="duplicate id"),
        ]
    )

    assert capsys.readouterr().out.splitlines() == [
        "        1.00ms  root  INTERNAL",
        "        1.00ms    duplicate id  INTERNAL",
    ]


def test_capture_available_rejects_a_third_party_tracer_provider(monkeypatch) -> None:
    # capture_spans mutates the provider's sampler and processor list, which
    # only works on the SDK's own provider (or the proxy it can replace). A
    # third-party provider must report unavailable rather than be crashed into.
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setattr("plain.cli._trace.trace.get_tracer_provider", lambda: object())
    assert capture_available() is False

    monkeypatch.setattr(
        "plain.cli._trace.trace.get_tracer_provider", lambda: TracerProvider()
    )
    assert capture_available() is True


def test_trace_note_states(monkeypatch) -> None:
    # Each unusable `traces` value gets exactly one truthful note, and a
    # readable trace gets none.
    monkeypatch.setattr("plain.cli.request.capture_available", lambda: False)
    assert _trace_note(None) == _TRACE_UNAVAILABLE

    monkeypatch.setattr("plain.cli.request.capture_available", lambda: True)
    assert _trace_note(None) == _TRACE_NOT_REACHED

    assert _trace_note([]) == _TRACE_EMPTY

    readable: list[CapturedTrace] = [
        {
            "name": "GET /",
            "request_id": None,
            "analysis": {
                "duration_ms": 1.0,
                "span_count": 1,
                "query_count": 0,
                "transaction_count": 0,
                "exceptions": [],
                "queries": [],
            },
            "spans": [],
        }
    ]
    assert _trace_note(readable) is None


def _captured_with_queries(queries: list) -> CapturedTrace:
    return {
        "name": "GET /",
        "request_id": None,
        "analysis": {
            "duration_ms": 1.0,
            "span_count": len(queries),
            "query_count": sum(q["count"] for q in queries),
            "transaction_count": 0,
            "exceptions": [],
            "queries": queries,
        },
        "spans": [],
    }


def test_display_cap_never_cuts_a_repeated_statement(monkeypatch, capsys) -> None:
    # The cap trims the singleton tail only. Ordered slowest-first, a fast but
    # many-times-repeated statement would fall past the cap — the one entry
    # the reader most needs — so it is always kept and only singletons count
    # toward "+ N more".
    monkeypatch.setattr("plain.cli.request._QUERY_LIST_LIMIT", 2)

    queries = [
        {
            "sql": "SELECT singleton_1",
            "count": 1,
            "total_duration_ms": 10.0,
            "sources": [],
        },
        {
            "sql": "SELECT singleton_2",
            "count": 1,
            "total_duration_ms": 8.0,
            "sources": [],
        },
        {
            "sql": "SELECT singleton_3",
            "count": 1,
            "total_duration_ms": 6.0,
            "sources": [],
        },
        {
            "sql": "SELECT repeated_marker",
            "count": 4,
            "total_duration_ms": 2.0,
            "sources": [],
        },
    ]

    _render_traces([_captured_with_queries(queries)], detailed=False)

    output = capsys.readouterr().out
    # The fast repeated statement survives the cap despite ranking last.
    assert "repeated_marker" in output
    # Only the one cut singleton is counted — not the kept repeat.
    assert "+ 1 more — see --trace" in output
    assert "singleton_3" not in output
