from __future__ import annotations

import json
import os
from typing import Any

import click

from plain.preflight import set_check_counts
from plain.runtime import settings
from plain.test import Client

from ._trace import (
    TraceAnalysis,
    TraceResult,
    analyze_trace,
    capture_available,
    capture_spans,
)

_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")

_TRACE_UNAVAILABLE = (
    "Trace capture skipped — opentelemetry-sdk is not installed. "
    "It ships with plain.observer, plain.connect, or plain.pytest."
)

# Cap on per-query lines shown in the text Trace section; the full list is
# always in --json.
_QUERY_LIST_LIMIT = 10


def _dispatch_request(
    client: Client, method: str, path: str, kwargs: dict[str, Any]
) -> Any:
    """Call the test client method matching the HTTP method."""
    if method not in _HTTP_METHODS:
        click.secho(f"Unsupported HTTP method: {method}", fg="red", err=True)
        raise SystemExit(1)
    return getattr(client, method.lower())(path, **kwargs)


def _truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def _format_source(source: str) -> str:
    """Shorten an absolute source path relative to the working directory."""
    cwd = os.getcwd()
    if source.startswith(cwd + os.sep):
        return source[len(cwd) + 1 :]
    return source


def _render_trace(analysis: TraceAnalysis) -> None:
    """Render the Trace section body — metrics, queries, and flagged issues."""
    click.echo(f"  Duration: {analysis['duration_ms']}ms")
    click.echo(f"  Spans: {analysis['span_count']}")

    duplicates = analysis["duplicate_query_count"]
    queries_line = f"  Queries: {analysis['query_count']}"
    if duplicates:
        plural = "" if duplicates == 1 else "s"
        queries_line += f" ({duplicates} duplicate{plural})"
    click.echo(queries_line)

    queries = analysis["queries"]
    for query in queries[:_QUERY_LIST_LIMIT]:
        sql = _truncate(" ".join(query["sql"].split()), 64)
        click.echo(f"    {query['count']}×  {query['total_duration_ms']}ms  {sql}")
    if len(queries) > _QUERY_LIST_LIMIT:
        click.echo(f"    + {len(queries) - _QUERY_LIST_LIMIT} more — see --json")

    issues = analysis["issues"]
    if issues:
        click.secho("  Issues:", fg="red", bold=True)
        for issue in issues:
            if issue["type"] == "n_plus_one":
                location = (
                    f"  {_format_source(issue['sources'][0])}"
                    if issue["sources"]
                    else ""
                )
                sql = _truncate(" ".join(issue["sql"].split()), 64)
                click.secho(f"    ⚠ N+1: {sql} ×{issue['count']}{location}", fg="red")
            elif issue["type"] == "exception":
                error_type = issue["error_type"] or "Exception"
                click.secho(f"    ⚠ {issue['description']} ({error_type})", fg="red")


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
    "--json",
    "output_json",
    is_flag=True,
    help="Output response metadata and trace analysis as JSON (no body)",
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
    output_json: bool,
) -> None:
    """Make HTTP requests against the dev database"""

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
        # is available (it ships with plain.observer / plain.connect /
        # plain.pytest, but is not a Plain core dependency).
        trace_result: TraceResult | None
        if capture_available():
            with capture_spans() as otel_exporter:
                response = _dispatch_request(client, method, path, kwargs)
            trace_result = analyze_trace(
                otel_exporter.get_finished_spans(), app_root=os.getcwd()
            )
        else:
            response = _dispatch_request(client, method, path, kwargs)
            trace_result = None

        # Run assertions (shared by text and JSON output)
        failed: list[str] = []

        if assert_status is not None:
            if response.status_code != assert_status:
                failed.append(
                    f"Expected status {assert_status}, got {response.status_code}"
                )
        elif response.status_code >= 500:
            failed.append(f"Server error: {response.status_code}")

        body_text = (
            response.content.decode("utf-8", errors="replace")
            if response.content
            else ""
        )

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
                "trace": trace_result,
            }
            if trace_result is None:
                json_output["trace_note"] = _TRACE_UNAVAILABLE
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

        # Trace — its own section, paralleling the JSON `trace` key
        click.echo()
        click.secho("Trace:", fg="yellow", bold=True)
        if trace_result is not None:
            _render_trace(trace_result["analysis"])
        else:
            click.echo("  skipped — opentelemetry-sdk not installed")

        click.echo()

        # Show headers
        if response.headers and not no_headers:
            click.secho("Response Headers:", fg="yellow", bold=True)
            for key, value in response.headers.items():
                click.echo(f"  {key}: {value}")
            click.echo()

        # Show response content last
        if response.content and not no_body:
            response_content_type = response.headers.get("Content-Type", "")

            if "json" in response_content_type.lower():
                try:
                    # The test client adds a json() method to the response
                    json_method = getattr(response, "json", None)
                    if json_method and callable(json_method):
                        json_data: Any = json_method()
                        click.secho("Response Body (JSON):", fg="yellow", bold=True)
                        click.echo(json.dumps(json_data, indent=2))
                    else:
                        click.secho("Response Body:", fg="yellow", bold=True)
                        click.echo(response.content.decode("utf-8", errors="replace"))
                except Exception:
                    click.secho("Response Body:", fg="yellow", bold=True)
                    click.echo(response.content.decode("utf-8", errors="replace"))
            elif "html" in response_content_type.lower():
                click.secho("Response Body (HTML):", fg="yellow", bold=True)
                content = response.content.decode("utf-8", errors="replace")
                click.echo(content)
            else:
                click.secho("Response Body:", fg="yellow", bold=True)
                content = response.content.decode("utf-8", errors="replace")
                click.echo(content)
        elif not no_body:
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
    except Exception as e:
        click.secho(f"Request failed: {e}", fg="red", err=True)
        raise SystemExit(1)
