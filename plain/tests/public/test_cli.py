from __future__ import annotations

import json
from unittest import mock

from click.testing import CliRunner

from plain.cli.core import cli
from plain.runtime import settings
from plain.urls.resolvers import _get_cached_resolver


def test_plain_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"], prog_name="plain")
    assert result.exit_code == 0
    assert result.output.startswith("Usage: plain")


def test_plain_urls_list_renders_both_modes():
    """`plain urls list` must render every URLPattern and URLResolver in the
    configured router without crashing. Pins both `--flat` and the default
    tree mode against `boundary_routers.BoundaryRouter`, which exercises
    both kinds (nested includes + endpoint patterns).

    Regression test: this used to AttributeError because the rendering loop
    read `pattern.pattern` after the resolver was rewritten to expose
    `raw_route`. ty couldn't catch the access because the parameter was
    annotated as bare `list`; both call sites are now typed
    `list[URLPattern | URLResolver]` so future renames blow up at
    type-check time.
    """
    original = settings.URLS_ROUTER
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = "boundary_routers.BoundaryRouter"
    settings.URLS_TRAILING_SLASH = True
    _get_cached_resolver.cache_clear()
    try:
        runner = CliRunner()

        tree = runner.invoke(cli, ["urls", "list"], prog_name="plain")
        assert tree.exit_code == 0, tree.output
        assert "admin-canonical" in tree.output
        # Tree mode should append the trailing slash on endpoint labels
        # so the displayed URL matches what `resolve()` accepts.
        assert "home/" in tree.output

        flat = runner.invoke(cli, ["urls", "list", "--flat"], prog_name="plain")
        assert flat.exit_code == 0, flat.output
        assert "admin-canonical" in flat.output
        # Under `URLS_TRAILING_SLASH=True`, canonical URLs end in `/`.
        # Flat rendering must produce `admin-canonical/home/` — not
        # `admin-canonicalhome/` (missing separator) and not
        # `admin-canonical/home` (missing trailing slash). Both were
        # regressions of the global-trailing-slash refactor.
        assert "admin-canonical/home/" in flat.output
        assert "admin-canonicalhome" not in flat.output
    finally:
        settings.URLS_ROUTER = original
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


def test_plain_request_streaming_response_does_not_crash():
    """`plain request` against a streaming/file response (e.g. an asset) must
    not crash. Streaming responses have no readable `.content` — accessing it
    raises AttributeError — so the command summarizes from headers instead of
    dumping the body.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/stream"], prog_name="plain")
    assert result.exit_code == 0, result.output
    assert "Status: 200" in result.output
    # Body is summarized, not dumped or crashed on.
    assert "streaming response" in result.output
    assert "text/plain" in result.output
    assert "streamed-bytes" not in result.output


def test_plain_request_streaming_body_assertion_is_flagged_unverifiable():
    """A body `--contains` assertion can't be checked on a streaming response
    (the body isn't readable), so it must fail loudly rather than silently pass.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli, ["request", "/stream", "--contains", "streamed"], prog_name="plain"
    )
    assert result.exit_code == 1, result.output
    assert "Cannot check body assertions on a streaming response" in result.output


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
    with mock.patch("plain.cli.request.analyze_traces", return_value=[]):
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


def test_plain_changelog_plain():
    runner = CliRunner()
    result = runner.invoke(cli, ["changelog", "plain"], prog_name="plain")
    assert result.exit_code == 0
    assert "0.50.0" in result.output


def test_plain_changelog_range_warning():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["changelog", "plain", "--from", "0.49.0", "--to", "0.50.0"],
        prog_name="plain",
    )
    assert result.exit_code == 0
    assert "0.50.0" in result.output
    assert "Warning" in result.output
