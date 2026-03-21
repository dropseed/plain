from __future__ import annotations

import json
from typing import Any

import click

from plain.cli import register_cli
from plain.observer.models import Span, Trace


@register_cli("observer")
@click.group("observer")
def observer_cli() -> None:
    """Observability and tracing tools"""


@observer_cli.command("request")
@click.argument("path")
@click.option(
    "--method",
    default="GET",
    help="HTTP method",
)
@click.option("--data", help="Request data (JSON string for POST/PUT/PATCH)")
@click.option(
    "--user",
    "user_id",
    help="User ID or email to authenticate as",
)
def observer_request(
    path: str,
    method: str,
    data: str | None,
    user_id: str | None,
) -> None:
    """Make an HTTP request and return trace analysis as JSON.

    Automatically enables tracing and returns structured performance
    analysis designed for AI agent consumption.
    """
    from plain.runtime import settings
    from plain.test import Client

    if not settings.DEBUG:
        click.secho("This command only works when DEBUG=True", fg="red", err=True)
        raise SystemExit(1)

    client = Client(raise_request_exception=False, headers={"Host": "localhost"})

    if user_id:
        try:
            from plain.auth import get_user_model
        except ImportError:
            raise click.UsageError("plain-auth is required to use --user")

        User = get_user_model()

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

    method = method.upper()
    kwargs: dict[str, Any] = {
        "follow": True,
        "headers": {"Accept": "text/html", "Observer": "persist"},
    }

    if method in ("POST", "PUT", "PATCH") and data:
        kwargs["data"] = data
        kwargs["content_type"] = "application/json"

    client_method = getattr(client, method.lower(), None)
    if not client_method:
        click.secho(f"Unsupported HTTP method: {method}", fg="red", err=True)
        raise SystemExit(1)

    try:
        response = client_method(path, **kwargs)
    except Exception as e:
        click.secho(f"Request failed: {e}", fg="red", err=True)
        raise SystemExit(1)

    request_id = response.request.unique_id
    trace = Trace.query.filter(request_id=request_id).first()

    if not trace:
        click.echo(
            json.dumps(
                {
                    "response": {"status": response.status_code},
                    "error": "No trace captured — is plain-observer installed and configured?",
                },
                indent=2,
            )
        )
        raise SystemExit(1)

    # Analyze spans
    spans = trace.spans.query.all().annotate_spans()  # type: ignore[attr-defined]

    # Group queries by SQL text
    queries_by_sql: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []

    for span in spans:
        sql = span.sql_query
        if not sql:
            # Check non-query spans for exceptions
            if stacktrace := span.get_exception_stacktrace():
                issues.append(
                    {
                        "type": "exception",
                        "description": f"Exception in {span.name}",
                        "span": span.name,
                        "stacktrace": stacktrace,
                    }
                )
            continue

        if sql not in queries_by_sql:
            queries_by_sql[sql] = {
                "sql": sql,
                "count": 0,
                "durations_ms": [],
                "sources": [],
            }
        entry = queries_by_sql[sql]
        entry["count"] += 1
        entry["durations_ms"].append(round(span.duration_ms(), 2))

        if loc := span.source_code_location:
            source = str(loc.get("File", ""))
            if "Line" in loc:
                source += f":{loc['Line']}"
            if "Function" in loc:
                source += f" in {loc['Function']}"
            if source and source not in entry["sources"]:
                entry["sources"].append(source)

    # Build sorted query list and detect duplicates
    queries: list[dict[str, Any]] = []
    query_count = 0
    duplicate_query_count = 0

    for q in sorted(
        queries_by_sql.values(),
        key=lambda x: (-x["count"], -sum(x["durations_ms"])),
    ):
        query_count += q["count"]
        if q["count"] > 1:
            duplicate_query_count += q["count"] - 1
            issues.insert(
                0,
                {
                    "type": "duplicate_query",
                    "description": f"Query executed {q['count']} times — likely N+1",
                    "sql": q["sql"],
                    "count": q["count"],
                    "total_duration_ms": round(sum(q["durations_ms"]), 2),
                    "sources": q["sources"],
                },
            )
        queries.append(
            {
                "sql": q["sql"],
                "count": q["count"],
                "total_duration_ms": round(sum(q["durations_ms"]), 2),
                "sources": q["sources"],
            }
        )

    # Build span tree
    span_dict = {s.span_id: s for s in spans}
    children_map: dict[str, list[str]] = {}
    for s in spans:
        if s.parent_id:
            children_map.setdefault(s.parent_id, []).append(s.span_id)

    def span_to_dict(span: Span) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": span.name,
            "duration_ms": round(span.duration_ms(), 2),
        }
        if span.sql_query:
            node["sql"] = span.sql_query
        if loc := span.source_code_location:
            source = str(loc.get("File", ""))
            if "Line" in loc:
                source += f":{loc['Line']}"
            if source:
                node["source"] = source
        if span.annotations:
            node["warnings"] = [a["message"] for a in span.annotations]
        if stacktrace := span.get_exception_stacktrace():
            node["exception"] = stacktrace
        if span.span_id in children_map:
            node["children"] = [
                span_to_dict(span_dict[cid])
                for cid in children_map[span.span_id]
                if cid in span_dict
            ]
        return node

    # Build output
    output: dict[str, Any] = {
        "response": {
            "status": response.status_code,
        },
        "trace": {
            "id": trace.trace_id,
            "duration_ms": round(trace.duration_ms(), 2),
            "query_count": query_count,
            "duplicate_query_count": duplicate_query_count,
        },
    }

    if response.resolver_match:
        match = response.resolver_match
        url_name = getattr(match, "namespaced_url_name", None) or getattr(
            match, "url_name", None
        )
        if url_name:
            output["response"]["url_pattern"] = url_name

    if issues:
        output["issues"] = issues

    output["queries"] = queries
    output["spans"] = [span_to_dict(s) for s in spans if not s.parent_id]

    logs = [
        {
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "message": log.message,
        }
        for log in trace.logs.query.all().order_by("timestamp")
    ]
    if logs:
        output["logs"] = logs

    click.echo(json.dumps(output, indent=2))

    if response.status_code >= 500:
        raise SystemExit(1)


@observer_cli.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def clear(force: bool) -> None:
    """Clear all observer data"""
    query = Trace.query.all()
    trace_count = query.count()

    if trace_count == 0:
        click.echo("No traces to clear.")
        return

    if not force:
        confirm_msg = f"Are you sure you want to clear {trace_count} trace(s)? This will delete all observer data."
        click.confirm(confirm_msg, abort=True)

    deleted_count, _ = query.delete()
    click.secho(f"✓ Cleared {deleted_count} traces and spans", fg="green")


@observer_cli.command("traces")
@click.option("--limit", default=20, help="Number of traces to show (default: 20)")
@click.option("--user-id", help="Filter by user ID")
@click.option("--request-id", help="Filter by request ID")
@click.option("--session-id", help="Filter by session ID")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def trace_list(
    limit: int,
    user_id: str | None,
    request_id: str | None,
    session_id: str | None,
    output_json: bool,
) -> None:
    """List recent traces"""
    # Build query
    query = Trace.query.all()

    if user_id:
        query = query.filter(user_id=user_id)
    if request_id:
        query = query.filter(request_id=request_id)
    if session_id:
        query = query.filter(session_id=session_id)

    # Limit results
    traces = list(query[:limit])

    if not traces:
        click.echo("No traces found.")
        return

    if output_json:
        # Output as JSON array
        output = []
        for trace in traces:
            output.append(
                {
                    "trace_id": trace.trace_id,
                    "start_time": trace.start_time.isoformat(),
                    "end_time": trace.end_time.isoformat(),
                    "duration_ms": trace.duration_ms(),
                    "request_id": trace.request_id,
                    "user_id": trace.user_id,
                    "session_id": trace.session_id,
                    "root_span_name": trace.root_span_name,
                    "summary": trace.summary,
                }
            )
        click.echo(json.dumps(output, indent=2))
    else:
        # Table-like output
        click.secho(
            f"Recent traces (showing {len(traces)} of {query.count()} total):",
            fg="bright_blue",
            bold=True,
        )
        click.echo()

        # Headers
        headers = [
            "Trace ID",
            "Start Time",
            "Summary",
            "Root Span",
            "Request ID",
            "User ID",
            "Session ID",
        ]
        col_widths = [41, 21, 31, 31, 22, 11, 22]

        # Print headers
        header_line = ""
        for header, width in zip(headers, col_widths):
            header_line += header.ljust(width)
        click.secho(header_line, bold=True)
        click.echo("-" * sum(col_widths))

        # Print traces
        for trace in traces:
            row = [
                trace.trace_id[:37] + "..."
                if len(trace.trace_id) > 40
                else trace.trace_id,
                trace.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                trace.summary[:27] + "..."
                if len(trace.summary) > 30
                else trace.summary,
                trace.root_span_name[:27] + "..."
                if len(trace.root_span_name) > 30
                else trace.root_span_name,
                trace.request_id[:18] + "..."
                if len(trace.request_id) > 20
                else trace.request_id,
                trace.user_id[:10],
                trace.session_id[:18] + "..."
                if len(trace.session_id) > 20
                else trace.session_id,
            ]

            row_line = ""
            for value, width in zip(row, col_widths):
                row_line += str(value).ljust(width)
            click.echo(row_line)


@observer_cli.command("trace")
@click.argument("trace_id")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def trace_detail(trace_id: str, output_json: bool) -> None:
    """Show detailed trace information"""
    try:
        trace = Trace.query.get(trace_id=trace_id)
    except Trace.DoesNotExist:
        click.secho(f"Error: Trace with ID '{trace_id}' not found", fg="red", err=True)
        raise click.Abort()

    if output_json:
        click.echo(json.dumps(trace.as_dict(), indent=2))
    else:
        click.echo(format_trace_output(trace))


@observer_cli.command("spans")
@click.option("--trace-id", help="Filter by trace ID")
@click.option("--limit", default=50, help="Number of spans to show (default: 50)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def span_list(trace_id: str | None, limit: int, output_json: bool) -> None:
    """List recent spans"""
    # Build query
    query = Span.query.all()

    if trace_id:
        query = query.filter(trace__trace_id=trace_id)

    # Limit results
    spans = list(query[:limit])

    if not spans:
        click.echo("No spans found.")
        return

    if output_json:
        # Output as JSON array
        output = []
        for span in spans:
            output.append(
                {
                    "span_id": span.span_id,
                    "trace_id": span.trace.trace_id,
                    "name": span.name,
                    "kind": span.kind,
                    "parent_id": span.parent_id,
                    "start_time": span.start_time.isoformat(),
                    "end_time": span.end_time.isoformat(),
                    "duration_ms": span.duration_ms(),
                    "status": span.status,
                }
            )
        click.echo(json.dumps(output, indent=2))
    else:
        # Table-like output
        click.secho(
            f"Recent spans (showing {len(spans)} of {query.count()} total):",
            fg="bright_blue",
            bold=True,
        )
        click.echo()

        # Headers
        headers = ["Span ID", "Trace ID", "Name", "Duration", "Kind", "Status"]
        col_widths = [22, 22, 41, 12, 12, 16]

        # Print headers
        header_line = ""
        for header, width in zip(headers, col_widths):
            header_line += header.ljust(width)
        click.secho(header_line, bold=True)
        click.echo("-" * sum(col_widths))

        # Print spans
        for span in spans:
            status_display = ""
            if span.status:
                if span.status in ["STATUS_CODE_OK", "OK"]:
                    status_display = "✓ OK"
                elif span.status not in ["STATUS_CODE_UNSET", "UNSET"]:
                    status_display = f"✗ {span.status}"

            row = [
                span.span_id[:18] + "..." if len(span.span_id) > 20 else span.span_id,
                span.trace.trace_id[:18] + "..."
                if len(span.trace.trace_id) > 20
                else span.trace.trace_id,
                span.name[:37] + "..." if len(span.name) > 40 else span.name,
                f"{span.duration_ms():.1f}ms",
                span.kind[:10],
                status_display[:15],
            ]

            # Build row with colored status
            row_parts = []
            for i, (value, width) in enumerate(zip(row, col_widths)):
                if i == 5:  # Status column
                    if span.status and span.status in ["STATUS_CODE_OK", "OK"]:
                        colored_value = click.style(str(value), fg="green")
                        # Need to account for the extra characters from coloring
                        padding = width - len(str(value))
                        row_parts.append(colored_value + " " * padding)
                    elif span.status and span.status not in [
                        "STATUS_CODE_UNSET",
                        "UNSET",
                        "",
                    ]:
                        colored_value = click.style(str(value), fg="red")
                        # Need to account for the extra characters from coloring
                        padding = width - len(str(value))
                        row_parts.append(colored_value + " " * padding)
                    else:
                        row_parts.append(str(value).ljust(width))
                else:
                    row_parts.append(str(value).ljust(width))

            click.echo("".join(row_parts))


@observer_cli.command("span")
@click.argument("span_id")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def span_detail(span_id: str, output_json: bool) -> None:
    """Show detailed span information"""
    try:
        span = Span.query.select_related("trace").get(span_id=span_id)
    except Span.DoesNotExist:
        click.secho(f"Error: Span with ID '{span_id}' not found", fg="red", err=True)
        raise click.Abort()

    if output_json:
        # Output as JSON
        click.echo(json.dumps(span.span_data, indent=2))
    else:
        # Detailed output
        label_width = 12
        click.secho(
            f"{'Span:':<{label_width}} {span.span_id}", fg="bright_blue", bold=True
        )
        click.echo(f"{'Trace:':<{label_width}} {span.trace.trace_id}")
        click.echo(f"{'Name:':<{label_width}} {span.name}")
        click.echo(f"{'Kind:':<{label_width}} {span.kind}")
        click.echo(
            f"{'Start:':<{label_width}} {span.start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
        )
        click.echo(
            f"{'End:':<{label_width}} {span.end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
        )
        click.echo(f"{'Duration:':<{label_width}} {span.duration_ms():.2f}ms")

        if span.parent_id:
            click.echo(f"{'Parent ID:':<{label_width}} {span.parent_id}")

        if span.status:
            status_color = "green" if span.status in ["STATUS_CODE_OK", "OK"] else "red"
            click.echo(f"{'Status:':<{label_width}} ", nl=False)
            click.secho(span.status, fg=status_color)

        # Show attributes
        if span.attributes:
            click.echo()
            click.secho("Attributes:", fg="bright_blue", bold=True)
            for key, value in span.attributes.items():
                # Format value based on type
                if isinstance(value, str) and len(value) > 100:
                    value = value[:97] + "..."
                click.echo(f"  {key}: {value}")

        # Show SQL query if present
        if span.sql_query:
            click.echo()
            click.secho("SQL Query:", fg="bright_blue", bold=True)
            formatted_sql = span.get_formatted_sql()
            if formatted_sql:
                for line in formatted_sql.split("\n"):
                    click.echo(f"  {line}")

            # Show query parameters
            if span.sql_query_params:
                click.echo()
                click.secho("Query Parameters:", fg="bright_blue", bold=True)
                for param, value in span.sql_query_params.items():
                    click.echo(f"  {param}: {value}")

        # Show events
        if span.events:
            click.echo()
            click.secho("Events:", fg="bright_blue", bold=True)
            for event in span.events:
                timestamp = span.format_event_timestamp(event.get("timestamp", ""))
                click.echo(f"  {event.get('name', 'unnamed')} at {timestamp}")
                if event.get("attributes"):
                    for key, value in event["attributes"].items():
                        # Special handling for stack traces
                        if key == "exception.stacktrace" and isinstance(value, str):
                            click.echo(f"    {key}:")
                            lines = value.split("\n")[:10]  # Show first 10 lines
                            for line in lines:
                                click.echo(f"      {line}")
                            if len(value.split("\n")) > 10:
                                click.echo("      ... (truncated)")
                        else:
                            click.echo(f"    {key}: {value}")

        # Show links
        if span.links:
            click.echo()
            click.secho("Links:", fg="bright_blue", bold=True)
            for link in span.links:
                click.echo(
                    f"  Trace: {link.get('context', {}).get('trace_id', 'unknown')}"
                )
                click.echo(
                    f"  Span: {link.get('context', {}).get('span_id', 'unknown')}"
                )
                if link.get("attributes"):
                    for key, value in link["attributes"].items():
                        click.echo(f"    {key}: {value}")


def format_trace_output(trace: Trace) -> str:
    """Format trace output for display - extracted for reuse."""
    output_lines: list[str] = []

    # Trace details with aligned labels
    label_width = 12
    start_time = trace.start_time
    end_time = trace.end_time
    output_lines.append(
        click.style(
            f"{'Trace:':<{label_width}} {trace.trace_id}", fg="bright_blue", bold=True
        )
    )
    output_lines.append(
        f"{'Start:':<{label_width}} {start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
    )
    output_lines.append(
        f"{'End:':<{label_width}} {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
    )
    output_lines.append(f"{'Duration:':<{label_width}} {trace.duration_ms():.2f}ms")

    if trace.summary:
        output_lines.append(f"{'Summary:':<{label_width}} {trace.summary}")

    if trace.request_id:
        output_lines.append(f"{'Request ID:':<{label_width}} {trace.request_id}")
    if trace.user_id:
        output_lines.append(f"{'User ID:':<{label_width}} {trace.user_id}")
    if trace.session_id:
        output_lines.append(f"{'Session ID:':<{label_width}} {trace.session_id}")

    output_lines.append("")
    output_lines.append(click.style("Spans:", fg="bright_blue", bold=True))

    # Get annotated spans with nesting levels
    spans = trace.spans.query.all().annotate_spans()  # type: ignore[attr-defined]

    # Build parent-child relationships
    span_dict = {span.span_id: span for span in spans}
    children: dict[str, list[str]] = {}
    for span in spans:
        if span.parent_id:
            children.setdefault(span.parent_id, []).append(span.span_id)

    def format_span_tree(span: Span, level: int = 0) -> list[str]:
        lines: list[str] = []
        # Simple 4-space indentation
        prefix = "    " * level

        # Span name with duration and status
        duration = span.duration_ms()

        # Determine status icon
        status_icon = ""
        if span.status:
            if span.status in ["STATUS_CODE_OK", "OK"]:
                status_icon = " ✓"
            elif span.status not in ["STATUS_CODE_UNSET", "UNSET"]:
                status_icon = " ✗"

        # Color based on span kind, but red if error
        if span.status and span.status not in [
            "STATUS_CODE_OK",
            "STATUS_CODE_UNSET",
            "OK",
            "UNSET",
        ]:
            color = "red"
        else:
            color_map = {
                "SERVER": "green",
                "CLIENT": "cyan",
                "INTERNAL": "white",
                "PRODUCER": "magenta",
                "CONSUMER": "yellow",
            }
            color = color_map.get(span.kind, "white")

        # Build span line
        span_line = (
            prefix
            + click.style(span.name, fg=color, bold=True, underline=True)
            + click.style(f" ({duration:.2f}ms){status_icon}", fg=color, bold=True)
            + click.style(f" [{span.span_id}]", fg="bright_black")
        )
        lines.append(span_line)

        # Show additional details with proper indentation
        detail_prefix = "    " * (level + 1)

        # Show SQL queries
        if span.sql_query:
            lines.append(
                f"{detail_prefix}SQL: {span.sql_query[:80]}{'...' if len(span.sql_query) > 80 else ''}"
            )

        # Show annotations (like duplicate queries)
        for annotation in span.annotations:
            severity_color = "yellow" if annotation["severity"] == "warning" else "red"
            lines.append(
                click.style(
                    f"{detail_prefix}⚠️  {annotation['message']}", fg=severity_color
                )
            )

        # Show exceptions
        if stacktrace := span.get_exception_stacktrace():
            lines.append(click.style(f"{detail_prefix}❌ Exception occurred", fg="red"))
            # Show first few lines of stacktrace
            stack_lines = stacktrace.split("\n")[:3]
            for line in stack_lines:
                if line.strip():
                    lines.append(f"{detail_prefix}   {line.strip()}")

        # Format children recursively
        if span.span_id in children:
            child_ids = children[span.span_id]
            for child_id in child_ids:
                child_span = span_dict[child_id]
                lines.extend(format_span_tree(child_span, level + 1))

        return lines

    # Start with root spans (spans without parents)
    root_spans = [span for span in spans if not span.parent_id]
    for root_span in root_spans:
        output_lines.extend(format_span_tree(root_span, 0))

    return "\n".join(output_lines)
