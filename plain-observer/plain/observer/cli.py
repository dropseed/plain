import json
import shlex
import subprocess
import sys
import urllib.request

import click

from plain.cli import register_cli
from plain.observer.models import Span, Trace


@register_cli("observer")
@click.group("observer")
def observer_cli():
    pass


@observer_cli.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def clear(force: bool):
    """Clear all observer data."""
    query = Trace.objects.all()
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
def trace_list(limit, user_id, request_id, session_id, output_json):
    """List recent traces."""
    # Build query
    query = Trace.objects.all()

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
def trace_detail(trace_id, output_json):
    """Display detailed information about a specific trace."""
    try:
        trace = Trace.objects.get(trace_id=trace_id)
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
def span_list(trace_id, limit, output_json):
    """List recent spans."""
    # Build query
    query = Span.objects.all()

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
def span_detail(span_id, output_json):
    """Display detailed information about a specific span."""
    try:
        span = Span.objects.select_related("trace").get(span_id=span_id)
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


def format_trace_output(trace):
    """Format trace output for display - extracted for reuse."""
    output_lines = []

    # Trace details with aligned labels
    label_width = 12
    output_lines.append(
        click.style(
            f"{'Trace:':<{label_width}} {trace.trace_id}", fg="bright_blue", bold=True
        )
    )
    output_lines.append(
        f"{'Start:':<{label_width}} {trace.start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
    )
    output_lines.append(
        f"{'End:':<{label_width}} {trace.end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
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
    spans = trace.spans.all().annotate_spans()

    # Build parent-child relationships
    span_dict = {span.span_id: span for span in spans}
    children = {}
    for span in spans:
        if span.parent_id:
            if span.parent_id not in children:
                children[span.parent_id] = []
            children[span.parent_id].append(span.span_id)

    def format_span_tree(span, level=0):
        lines = []
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


@observer_cli.command("diagnose")
@click.argument("trace_id", required=False)
@click.option("--url", help="Fetch trace from a shareable URL")
@click.option(
    "--json", "json_input", help="Provide trace JSON data (use '-' for stdin)"
)
@click.option(
    "--agent-command",
    envvar="PLAIN_AGENT_COMMAND",
    help="Run command with generated prompt",
)
def diagnose(trace_id, url, json_input, agent_command):
    """Generate a diagnostic prompt for analyzing a trace.

    By default, provide a trace ID from the database. Use --url for a shareable
    trace URL, or --json for raw trace data (--json - reads from stdin).
    """

    input_count = sum(bool(x) for x in [trace_id, url, json_input])
    if input_count == 0:
        raise click.UsageError("Must provide trace ID, --url, or --json")
    elif input_count > 1:
        raise click.UsageError("Cannot specify multiple input methods")

    if json_input:
        if json_input == "-":
            try:
                json_data = sys.stdin.read()
                trace_data = json.loads(json_data)
            except json.JSONDecodeError as e:
                raise click.ClickException(f"Error parsing JSON from stdin: {e}")
            except Exception as e:
                raise click.ClickException(f"Error reading from stdin: {e}")
        else:
            try:
                trace_data = json.loads(json_input)
            except json.JSONDecodeError as e:
                raise click.ClickException(f"Error parsing JSON: {e}")
    elif url:
        try:
            request = urllib.request.Request(
                url, headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(request) as response:
                trace_data = json.loads(response.read().decode())
        except Exception as e:
            raise click.ClickException(f"Error fetching trace from URL: {e}")
    else:
        try:
            trace = Trace.objects.get(trace_id=trace_id)
            trace_data = trace.as_dict()
        except Trace.DoesNotExist:
            raise click.ClickException(f"Trace with ID '{trace_id}' not found")

    prompt_lines = [
        "I have an OpenTelemetry trace data JSON from a Plain application. Analyze it for performance issues or improvements.",
        "",
        "Focus on easy and obvious wins first and foremost. If there is nothing obvious, that's ok! Tell me that and ask whether there are specific things we should look deeper into.",
        "",
        "If potential code changes are found, briefly explain them and ask whether we should implement them.",
        "",
        "## Trace Data JSON",
        "",
        "```json",
        json.dumps(trace_data, indent=2),
        "```",
    ]

    prompt = "\n".join(prompt_lines)

    if agent_command:
        cmd = shlex.split(agent_command)
        cmd.append(prompt)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            click.secho(
                f"Agent command failed with exit code {result.returncode}",
                fg="red",
                err=True,
            )
    else:
        click.echo(prompt)
        click.secho(
            "\nCopy the prompt above to a coding agent. To run an agent automatically, use --agent-command or set the PLAIN_AGENT_COMMAND environment variable.",
            dim=True,
            italic=True,
            err=True,
        )
