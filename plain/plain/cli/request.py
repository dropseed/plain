from __future__ import annotations

import json
import os
import sys
from typing import Any

import click

from plain.preflight import set_check_counts
from plain.runtime import settings
from plain.test import Client

from ._trace import (
    CapturedTrace,
    RawSpan,
    analyze_traces,
    capture_available,
    capture_spans,
)

_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")

_TRACE_UNAVAILABLE = (
    "Trace capture skipped — it needs the OpenTelemetry SDK, which ships with "
    "plain.connect or plain.pytest."
)

_TRACE_EMPTY = (
    "No spans were captured. Tracing may be turned off in this environment "
    "(for example OTEL_SDK_DISABLED)."
)

_TRACE_NOT_REACHED = (
    "The request failed before it was dispatched, so there is no trace."
)


def _trace_note(traces: list[CapturedTrace] | None) -> str | None:
    """Explain an unusable `traces`, or None when there is a trace to read.

    Anything that indexes into `traces` needs something to report instead of
    an IndexError. `traces is None` with the SDK unavailable means capture was
    skipped; with the SDK available it means dispatch was never reached, since
    the analyzer runs unconditionally and any bug in it now propagates rather
    than being folded into this note.
    """
    if traces is None:
        return _TRACE_UNAVAILABLE if not capture_available() else _TRACE_NOT_REACHED
    if not traces:
        return _TRACE_EMPTY
    return None


# Cap on per-query lines shown in the text Trace section. `--trace` lifts it;
# `--json` is never capped.
_QUERY_LIST_LIMIT = 10

# Width SQL is elided to in the terminal.
_SQL_DISPLAY_WIDTH = 64


def _dispatch_request(
    client: Client, method: str, path: str, kwargs: dict[str, Any]
) -> Any:
    """Call the test client method matching the HTTP method."""
    if method not in _HTTP_METHODS:
        click.secho(f"Unsupported HTTP method: {method}", fg="red", err=True)
        raise SystemExit(1)
    return getattr(client, method.lower())(path, **kwargs)


def _display_sql(sql: str) -> str:
    """Collapse a statement to one elided line for the terminal.

    The middle goes rather than the tail. A wide SELECT is mostly column
    list, so two statements against different tables share a long prefix and
    elide to the same string — it is the FROM and WHERE at the end that tell
    them apart.
    """
    one_line = " ".join(sql.split())
    if len(one_line) <= _SQL_DISPLAY_WIDTH:
        return one_line
    head = _SQL_DISPLAY_WIDTH * 3 // 5
    tail = _SQL_DISPLAY_WIDTH - head - 1
    return f"{one_line[:head]}…{one_line[-tail:]}"


def _installed_package_path(path: str) -> str | None:
    """The path below `site-packages`, or None when this is not a dependency.

    Used only to shorten an installed dependency's call site for display.
    """
    _, marker, package_path = path.rpartition(f"site-packages{os.sep}")
    return package_path if marker else None


def _format_source(source: str) -> str:
    """Shorten a source location for display.

    An installed dependency collapses to its package path; anything else is
    shown relative to the working directory when that comes out shorter, which
    keeps sibling checkouts readable without inventing `../../..` chains for
    paths in a different tree entirely.

    This asks whether the path is *installed*, not whether it is app code —
    a sibling checkout is neither, and wants the relative form.
    """
    if (installed_path := _installed_package_path(source)) is not None:
        return installed_path
    try:
        relative = os.path.relpath(source, os.getcwd())
    except ValueError:  # different drive on Windows
        return source
    return relative if len(relative) < len(source) else source


def _echo_span(span: RawSpan, *, depth: int) -> None:
    """Print one row of the span tree, indented to its depth."""
    name = f"{'  ' * depth}{span['name']}"
    if span.get("status") == "ERROR":
        name = click.style(name, fg="red")
    kind = click.style(f"  {span['kind']}", dim=True)
    click.echo(f"    {span['duration_ms']:>8.2f}ms  {name}{kind}")


def _render_span_tree(spans: list[RawSpan]) -> None:
    """Print one trace's spans as an indented tree, parents before children.

    Spans arrive flat and ordered by start time; `parent_span_id` gives the
    structure. A span whose parent was not captured — the parent hadn't ended
    when capture stopped — is rendered as a root rather than dropped.
    """
    captured_ids = {span["span_id"] for span in spans}
    children: dict[str | None, list[RawSpan]] = {}
    for span in spans:
        parent = span["parent_span_id"]
        if parent not in captured_ids:
            parent = None
        children.setdefault(parent, []).append(span)

    # Malformed instrumentation (a self-parented span, or two spans sharing an
    # id) would otherwise recurse forever. Tracked by identity rather than by
    # span_id so that duplicate ids still each get rendered exactly once.
    rendered: set[int] = set()

    def render(parent_id: str | None, depth: int) -> None:
        for span in children.get(parent_id, []):
            if id(span) in rendered:
                continue
            rendered.add(id(span))
            _echo_span(span, depth=depth)
            render(span["span_id"], depth + 1)

    render(None, 0)
    # Anything left is unreachable from a root (a parent cycle). Print it flat
    # rather than silently dropping spans the count above already promised.
    for span in spans:
        if id(span) not in rendered:
            _echo_span(span, depth=0)


def _render_trace(*, captured: CapturedTrace, detailed: bool, show_hint: bool) -> None:
    """Render one trace's body — metrics, queries, and recorded exceptions.

    Every listed statement names its call sites. When `detailed`, the query
    list is uncapped and the full span tree is printed after the exceptions.
    `show_hint` advertises `--trace`, and is set on one block only however
    many traces were captured.
    """
    analysis = captured["analysis"]

    click.echo(f"  Duration: {analysis['duration_ms']:.2f}ms")

    spans_line = f"  Spans: {analysis['span_count']}"
    if show_hint:
        spans_line += click.style("  (--trace for the span tree)", dim=True)
    click.echo(spans_line)

    queries_line = f"  Queries: {analysis['query_count']}"
    if transactions := analysis["transaction_count"]:
        plural = "" if transactions == 1 else "s"
        queries_line += click.style(
            f"  +{transactions} transaction statement{plural}", dim=True
        )
    click.echo(queries_line)

    queries = analysis["queries"]
    if detailed:
        shown = queries
    else:
        # The cap trims the singleton tail only. Duration-first order would
        # otherwise push a fast, many-times-repeated statement below the cap —
        # the one entry the reader most needs to see.
        shown = queries[:_QUERY_LIST_LIMIT] + [
            q for q in queries[_QUERY_LIST_LIMIT:] if q["count"] > 1
        ]
    for query in shown:
        sql = _display_sql(query["sql"])
        click.echo(
            f"    {query['count']:>3}×  {query['total_duration_ms']:>7.2f}ms  {sql}"
        )
        # Truncated SQL alone rarely identifies a wide SELECT — the call site
        # does, and two wide SELECTs can elide to the same string. Every
        # listed statement names its call sites.
        for source in query["sources"]:
            click.echo(f"      → {_format_source(source)}")
    if len(queries) > len(shown):
        click.echo(f"    + {len(queries) - len(shown)} more — see --trace")

    if exceptions := analysis["exceptions"]:
        click.secho("  Exceptions:", fg="red", bold=True)
        for exception in exceptions:
            error_type = exception["error_type"] or "Exception"
            click.secho(f"    ⚠ {error_type} in {exception['span']}", fg="red")
            if message := exception["message"]:
                click.secho(f"      {message}", fg="red")

    if detailed:
        click.echo("  Span tree:")
        _render_span_tree(captured["spans"])


def _render_traces(traces: list[CapturedTrace] | None, *, detailed: bool) -> None:
    """Render the Trace section — one block per captured trace.

    A followed redirect chain is several requests, so it gets several blocks
    rather than one merged summary that would double-count anything the
    framework does on every request.
    """
    if not traces:
        click.secho("Trace:", fg="yellow", bold=True)
        click.echo(f"  {_trace_note(traces)}")
        return

    for index, captured in enumerate(traces, start=1):
        if index > 1:
            click.echo()
        label = (
            "Trace:"
            if len(traces) == 1
            else f"Trace ({index}/{len(traces)}): {captured['name']}"
        )
        click.secho(label, fg="yellow", bold=True)
        _render_trace(
            captured=captured,
            detailed=detailed,
            show_hint=not detailed and index == 1,
        )


@click.command()
@click.argument("path")
@click.option(
    "--method",
    default="GET",
    help="HTTP method (GET, POST, PUT, PATCH, DELETE, etc.)",
)
@click.option(
    "--data",
    help="Request body for POST/PUT/PATCH (form-encoded by default, e.g. 'key=val&key2=val2')",
)
@click.option(
    "--user",
    "user_id",
    help="User ID or email to authenticate as (skips normal authentication)",
)
@click.option(
    "--follow/--no-follow",
    default=True,
    help="Follow redirects (default: True)",
)
@click.option(
    "--content-type",
    help="Content-Type header for request data",
)
@click.option(
    "--header",
    "headers",
    multiple=True,
    help="Additional headers (format: 'Name: Value')",
)
@click.option(
    "--no-headers",
    is_flag=True,
    help="Hide response headers from output",
)
@click.option(
    "--no-body",
    is_flag=True,
    help="Hide response body from output",
)
@click.option(
    "--status",
    "assert_status",
    type=int,
    default=None,
    help="Assert response status code equals this value",
)
@click.option(
    "--contains",
    "assert_contains",
    multiple=True,
    help="Assert response body contains this text (repeatable)",
)
@click.option(
    "--not-contains",
    "assert_not_contains",
    multiple=True,
    help="Assert response body does not contain this text (repeatable)",
)
@click.option(
    "--trace",
    "show_trace",
    is_flag=True,
    help=(
        "Show the full trace in the text output — the complete query list and "
        "the span tree. --json always includes it."
    ),
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output response metadata and the full trace as JSON (no body)",
)
def request(
    path: str,
    method: str,
    data: str | None,
    user_id: str | None,
    follow: bool,
    content_type: str | None,
    headers: tuple[str, ...],
    no_headers: bool,
    no_body: bool,
    assert_status: int | None,
    assert_contains: tuple[str, ...],
    assert_not_contains: tuple[str, ...],
    show_trace: bool,
    output_json: bool,
) -> None:
    """Make HTTP requests against the dev database"""

    # Bound before the try so the failure handler can report a trace even
    # when the request never got as far as capturing one.
    traces: list[CapturedTrace] | None = None
    traces_rendered = False

    try:
        # Only allow in DEBUG mode for security
        if not settings.DEBUG:
            click.secho("This command only works when DEBUG=True", fg="red", err=True)
            raise SystemExit(1)

        # Create test client
        client = Client(headers={"Host": "localhost"})

        if user_id:
            try:
                from app.users.models import User
            except ImportError:
                raise click.UsageError(
                    "app.users.models.User is required to use --user"
                )

            user = None
            try:
                user = User.query.get(id=user_id)
            except (User.DoesNotExist, ValueError):
                pass

            if user is None:
                try:
                    user = User.query.get(email=user_id)
                except User.DoesNotExist:
                    pass

            if user is None:
                click.secho(f"User not found: {user_id}", fg="red", err=True)
                raise SystemExit(1)

            client.force_login(user)

        # Parse additional headers (default Accept to text/html)
        header_dict = {"Accept": "text/html"}
        for header in headers:
            if ":" in header:
                key, value = header.split(":", 1)
                header_dict[key.strip()] = value.strip()

        # Auto-detect content type if not specified
        if data and not content_type:
            stripped = data.strip()
            if stripped.startswith(("{", "[")):
                content_type = "application/json"
            else:
                content_type = "application/x-www-form-urlencoded"

        # Validate JSON data
        if data and content_type and "json" in content_type.lower():
            try:
                json.loads(data)
            except json.JSONDecodeError as e:
                click.secho(f"Invalid JSON data: {e}", fg="red", err=True)
                raise SystemExit(1)

        # Make the request
        method = method.upper()
        kwargs: dict[str, Any] = {
            "follow": follow,
        }
        kwargs["headers"] = header_dict

        if method in ("POST", "PUT", "PATCH") and data:
            kwargs["data"] = data
            if content_type:
                kwargs["content_type"] = content_type

        # The admin toolbar's preflight badge otherwise runs the full preflight
        # suite on first render, landing those queries in the captured trace.
        set_check_counts(errors=0, warnings=0)

        # Dispatch the request, capturing a trace when the OpenTelemetry SDK
        # is available (it ships with plain.connect / plain.pytest, but is
        # not a Plain core dependency).
        if capture_available():
            with capture_spans() as otel_exporter:
                try:
                    response = _dispatch_request(client, method, path, kwargs)
                finally:
                    # Analyze in a `finally` so a view that raises still leaves
                    # a trace behind — that is the request you most want one
                    # for. Spans are exported as they end, so the ones that
                    # completed before the raise are already here.
                    traces = analyze_traces(otel_exporter.get_finished_spans())
        else:
            response = _dispatch_request(client, method, path, kwargs)

        # Run assertions (shared by text and JSON output)
        failed: list[str] = []

        if assert_status is not None:
            if response.status_code != assert_status:
                failed.append(
                    f"Expected status {assert_status}, got {response.status_code}"
                )
        elif response.status_code >= 500:
            failed.append(f"Server error: {response.status_code}")

        # Streaming/file responses (e.g. assets) have no readable `.content` —
        # the underlying file is already closed by the time we get here, so only
        # metadata is available. Skip body assertions, but flag them so a
        # `--contains` isn't silently treated as passing.
        if response.streaming:
            body_text = None
            if assert_contains or assert_not_contains:
                failed.append("Cannot check body assertions on a streaming response")
        else:
            body_text = response.content.decode("utf-8", errors="replace")

            for text in assert_contains:
                if text not in body_text:
                    failed.append(f"Response body does not contain: {text}")

            for text in assert_not_contains:
                if text in body_text:
                    failed.append(f"Response body contains: {text}")

        if output_json:
            response_data: dict[str, Any] = {
                "status": response.status_code,
                "request_id": response.request.unique_id,
            }
            response_data["user"] = (
                str(response.user) if getattr(response, "user", None) else None
            )
            redirects = getattr(response, "redirect_chain", None)
            if redirects:
                response_data["redirects"] = [
                    {"url": url, "status": status} for url, status in redirects
                ]
            if response.resolver_match:
                resolver_match = response.resolver_match
                url_name = getattr(
                    resolver_match, "namespaced_url_name", None
                ) or getattr(resolver_match, "url_name", None)
                if url_name:
                    response_data["url_pattern"] = url_name
            if response.headers:
                response_data["headers"] = dict(response.headers)
            json_output: dict[str, Any] = {
                "response": response_data,
                "traces": traces,
            }
            if note := _trace_note(traces):
                json_output["trace_note"] = note
            if failed:
                json_output["assertion_failures"] = failed
            click.echo(json.dumps(json_output, indent=2))
            if failed:
                raise SystemExit(1)
            return

        # Display response information
        click.secho("Response:", fg="yellow", bold=True)

        # Status code
        click.echo(f"  Status: {response.status_code}")

        # Request ID
        click.echo(f"  Request ID: {response.request.unique_id}")

        # Surface followed redirects — a 200 may not be the path you asked for.
        redirects = getattr(response, "redirect_chain", None)
        if redirects:
            hops = " → ".join(
                [path] + [f"{url} ({status})" for url, status in redirects]
            )
            click.secho(f"  Redirected: {hops}", fg="yellow")

        # URL pattern
        if response.resolver_match:
            match = response.resolver_match
            namespaced_url_name = getattr(match, "namespaced_url_name", None)
            url_name_attr = getattr(match, "url_name", None)
            url_name = namespaced_url_name or url_name_attr
            if url_name:
                click.echo(f"  URL pattern: {url_name}")

        # Always show auth state — authed vs anonymous should never be ambiguous.
        if getattr(response, "user", None):
            click.echo(f"  User: {response.user}")
        else:
            click.echo("  User: anonymous")

        # Trace — its own section, paralleling the JSON `traces` key
        click.echo()
        # Set before rendering so a partial render isn't duplicated by the
        # failure handler if `_render_traces` raises partway through.
        traces_rendered = True
        _render_traces(traces, detailed=show_trace)

        click.echo()

        # Show headers
        if response.headers and not no_headers:
            click.secho("Response Headers:", fg="yellow", bold=True)
            for key, value in response.headers.items():
                click.echo(f"  {key}: {value}")
            click.echo()

        # Show response content last
        if no_body:
            pass
        elif response.streaming:
            # Streaming/file responses (e.g. assets): the body isn't readable
            # here, so summarize from headers instead of dumping it.
            click.secho("Response Body:", fg="yellow", bold=True)
            content_type = response.headers.get("Content-Type", "") or "unknown"
            length = response.headers.get("Content-Length")
            size = f"{length} bytes" if length else "unknown size"
            click.echo(f"  (streaming response: {content_type}, {size})")
        elif body_text:
            content_type = response.headers.get("Content-Type", "").lower()

            # Default: print the decoded body under a generic header. JSON is
            # pretty-printed; HTML and everything else print as-is.
            header = "Response Body:"
            output = body_text

            if "json" in content_type:
                # The test client adds a json() method to the response.
                json_method = getattr(response, "json", None)
                if callable(json_method):
                    try:
                        output = json.dumps(json_method(), indent=2)
                        header = "Response Body (JSON):"
                    except Exception:
                        pass  # fall back to the raw decoded body
            elif "html" in content_type:
                header = "Response Body (HTML):"

            click.secho(header, fg="yellow", bold=True)
            click.echo(output)
        else:
            click.secho("(No response body)", fg="yellow", dim=True)

        # Report assertion failures
        if failed:
            click.echo()
            click.secho("Assertions failed:", fg="red", bold=True)
            for msg in failed:
                click.secho(f"  ✗ {msg}", fg="red")
            raise SystemExit(1)

    except SystemExit:
        raise
    except BrokenPipeError:
        # Downstream closed the pipe (`| head`) — not a failure. Point stdout
        # at devnull so the interpreter's shutdown flush doesn't raise again.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
    except Exception as e:
        click.secho(f"Request failed: {e}", fg="red", err=True)
        # A failed request still captured a trace, and it is the one worth
        # reading. Report it in whichever shape was asked for rather than
        # exiting with nothing on stdout.
        if output_json:
            failure: dict[str, Any] = {"error": str(e), "traces": traces}
            if note := _trace_note(traces):
                failure["trace_note"] = note
            click.echo(json.dumps(failure, indent=2))
        elif traces is not None and not traces_rendered:
            # Only when a request actually ran — a usage error has no trace to
            # discuss, and a Trace section would be the whole of stdout.
            click.echo()
            _render_traces(traces, detailed=show_trace)
        raise SystemExit(1)
