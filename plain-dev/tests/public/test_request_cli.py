"""`plain request`, run the way a user runs it: through the `plain` command."""

import json
from unittest import mock

from click.testing import CliRunner
from plain.cli.core import cli


def test_plain_request_streaming_response_is_summarized():
    """`plain request` against a streaming/file response (e.g. an asset)
    summarizes the body — type and size — instead of dumping what may be a
    large or binary download.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/stream"], prog_name="plain")
    assert result.exit_code == 0, result.output
    assert "Status: 200" in result.output
    assert "streaming response: text/plain" in result.output
    assert "14 bytes" in result.output
    assert "streamed-bytes" not in result.output


def test_plain_request_checks_body_assertions_on_a_streaming_response():
    """The streamed body is read, so `--contains` checks it for real — a
    match passes and a miss fails."""
    runner = CliRunner()

    found = runner.invoke(
        cli,
        ["request", "/stream-generator", "--contains", "line 2"],
        prog_name="plain",
    )
    assert found.exit_code == 0, found.output

    missing = runner.invoke(
        cli,
        ["request", "/stream-generator", "--contains", "line 3"],
        prog_name="plain",
    )
    assert missing.exit_code == 1, missing.output
    assert "Response body does not contain: line 3" in missing.output


def test_plain_request_trace_flag_shows_the_span_tree():
    """`--trace` renders the captured spans as a tree. Without it the summary
    only reports a span count, so the flag has to be advertised — it is the
    only way to see the tree without reading `--json`.
    """
    runner = CliRunner()

    summary = runner.invoke(
        cli, ["request", "/", "--no-body", "--no-headers"], prog_name="plain"
    )
    assert summary.exit_code == 0, summary.output
    assert "Span tree:" not in summary.output
    assert "--trace for the span tree" in summary.output

    detailed = runner.invoke(
        cli, ["request", "/", "--trace", "--no-body", "--no-headers"], prog_name="plain"
    )
    assert detailed.exit_code == 0, detailed.output
    assert "Span tree:" in detailed.output
    # The request's own entry span is always captured.
    assert "GET /  SERVER" in detailed.output
    assert "--trace for the span tree" not in detailed.output


def test_plain_request_shows_call_sites_for_every_listed_statement():
    """Every listed statement names its call sites, in every mode.

    The path itself tells the reader whose code ran it — no app/dependency
    flag is drawn. The tool reports every site (the call site, not the
    truncated SQL, is what identifies a wide SELECT: two of them can elide to
    the same string) and shortens paths for readability — a dependency to its
    package path, a project file relative to the working directory.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli, ["request", "/queries", "--no-body", "--no-headers"], prog_name="plain"
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    # Both call sites for the 4×-repeated statement are listed right under it —
    # the dependency's one execution and the app's three, shown in run order.
    repeated = next(i for i, line in enumerate(lines) if "4×" in line)
    sites = lines[repeated + 1 : repeated + 3]
    assert any("→ app/views.py:41 in index" in line for line in sites)
    assert any(
        "→ plain/sessions/core.py:92 in _get_session_data" in line for line in sites
    )
    # The statement that ran once is named too.
    assert "→ app/views.py:52 in index" in result.output
    # The dependency site is shortened to its package path, no site-packages prefix.
    assert ".venv" not in result.output
    # Styling is stripped when stdout is not a terminal — the normal case.
    assert "\x1b[" not in result.output


def test_plain_request_counts_transaction_statements_apart_from_queries():
    """Savepoint bookkeeping is reported, but never as a query."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["request", "/queries", "--no-body", "--no-headers"], prog_name="plain"
    )

    assert result.exit_code == 0, result.output
    assert "Queries: 5" in result.output
    assert "+1 transaction statement" in result.output
    assert "SAVEPOINT" not in result.output


def test_plain_request_reports_an_exception_without_diagnosing_it():
    """Exceptions are surfaced; repeats are left for the reader to judge."""
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/boom", "--no-body"], prog_name="plain")

    assert result.exit_code == 1
    assert "Exceptions:" in result.stdout
    assert "ValueError in GET /boom" in result.stdout
    assert "kaboom" in result.stdout


def test_plain_request_json_reports_traces_and_call_sites():
    """The `--json` contract: a list of traces, each query with its sources."""
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/queries", "--json"], prog_name="plain")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["response"]["status"] == 200

    traces = payload["traces"]
    assert len(traces) == 1
    captured = traces[0]
    assert captured["name"] == "GET /queries"
    # Joins the trace back to the response the CLI reported for it.
    assert captured["request_id"] == payload["response"]["request_id"]

    analysis = captured["analysis"]
    assert analysis["query_count"] == 5
    assert analysis["transaction_count"] == 1
    assert analysis["exceptions"] == []

    # The repeated statement is one entry counting every execution, and
    # `sources` lists each distinct call site as a location string.
    repeated = next(q for q in analysis["queries"] if q["count"] > 1)
    assert repeated["count"] == 4
    assert len(repeated["sources"]) == 2
    assert any("app/views.py:41" in source for source in repeated["sources"])
    assert any("sessions/core.py:92" in source for source in repeated["sources"])

    # Slowest first, so a one-off slow query can't be crowded out by repeats.
    durations = [q["total_duration_ms"] for q in analysis["queries"]]
    assert durations == sorted(durations, reverse=True)


def test_plain_request_json_explains_an_unusable_trace():
    """An empty `traces` gets a note, so a consumer indexing it can say why."""
    runner = CliRunner()
    with mock.patch("plain.dev.request.cli.analyze_traces", return_value=[]):
        result = runner.invoke(cli, ["request", "/", "--json"], prog_name="plain")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["traces"] == []
    assert "trace_note" in payload


def test_plain_request_keeps_the_trace_when_the_view_raises():
    """A failed request still reports its trace — that is the one you want.

    The analysis used to run after the capture block, so an exception threw
    away every span and the command exited with nothing on stdout.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/boom", "--json"], prog_name="plain")

    assert result.exit_code == 1
    # The traceback goes to stderr, so stdout stays parseable for `| jq`.
    payload = json.loads(result.stdout)
    assert "kaboom" in payload["error"]
    assert payload["traces"], "the trace captured before the raise was discarded"
    assert payload["traces"][0]["name"] == "GET /boom"
