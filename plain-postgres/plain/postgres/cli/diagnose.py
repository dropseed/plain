from __future__ import annotations

import json
import sys
import textwrap
from typing import Any

import click

from ..db import get_connection
from ..introspection import CheckItem, CheckResult, build_table_owners, run_all_checks
from .decorators import database_management_command


def _detail_header_and_body(detail: str, body_indent: int) -> tuple[str, str]:
    """Split a possibly multi-line detail into a one-line header (for the
    item's render line) and a re-indented body (printed beneath).

    ``missing_index_candidates`` packs a per-query pg_stat_statements
    drill-down into ``detail`` via embedded newlines. Without this, the
    CLI wraps the whole blob in parens/em-dashes and the closing punctuation
    ends up several lines away from the opening one, making the output hard
    to read. Splitting at the first newline keeps the header tidy and
    re-indents the body under the item.
    """
    if "\n" not in detail:
        return detail, ""
    head, tail = detail.split("\n", 1)
    body = textwrap.indent(textwrap.dedent(tail).rstrip("\n"), " " * body_indent)
    return head, body


STATUS_SYMBOLS = {
    "ok": ("✓", "green"),
    "warning": ("!", "yellow"),
    "critical": ("!!", "red"),
    "skipped": ("—", None),
    "error": ("✗", "red"),
}


def format_human(
    results: list[CheckResult],
    context: dict[str, Any],
    *,
    show_all: bool = False,
    verbose: bool = False,
) -> None:
    def _actionable_items(r: CheckResult) -> list[CheckItem]:
        return [i for i in r["items"] if i["source"] != "package"]

    def _package_items(r: CheckResult) -> list[CheckItem]:
        return [i for i in r["items"] if i["source"] == "package"]

    def _effective_status(r: CheckResult) -> str:
        if show_all:
            return r["status"]
        if r["status"] in ("ok", "skipped", "error"):
            return r["status"]
        if r["items"] and not _actionable_items(r):
            return "ok"
        return r["status"]

    # Partition by tier. "warning" tier = things the user can fix in code or as
    # an app-level action. "operational" tier = DB-state facts (stats freshness,
    # bloat) whose remedies live outside Plain today. Operational findings are
    # shown as context, never as alarms.
    warning_results = [r for r in results if r["tier"] == "warning"]
    operational_results = [r for r in results if r["tier"] == "operational"]

    # ===== Warning tier summary =====
    warning_statuses = [_effective_status(r) for r in warning_results]
    ok_count = warning_statuses.count("ok")

    # In verbose mode, the summary covers every check (warning + operational)
    # so users see that e.g. index_bloat ran and passed. Non-verbose mode still
    # hides operational rows — they render under "Operational context" below.
    if verbose:
        summary_rows = [(r, _effective_status(r)) for r in results]
    else:
        summary_rows = [
            (r, s) for r, s in zip(warning_results, warning_statuses) if s != "ok"
        ]

    click.echo()
    if summary_rows:
        label_width = max(len(r["label"]) for r, _ in summary_rows)
        for r, status in summary_rows:
            summary_text = r["summary"] if status == r["status"] else "ok"
            symbol, color = STATUS_SYMBOLS.get(status, ("?", None))
            label = r["label"].ljust(label_width)
            click.echo(f"  {label}  {summary_text}  ", nl=False)
            click.secho(symbol, fg=color)

    if not verbose and ok_count:
        passing = [
            r["label"] for r, s in zip(warning_results, warning_statuses) if s == "ok"
        ]
        if len(passing) <= 5:
            passing_str = ", ".join(passing)
        else:
            passing_str = ", ".join(passing[:4]) + f", +{len(passing) - 4} more"
        click.secho(f"  {ok_count} checks passed: {passing_str}", dim=True)

    if verbose:
        all_statuses = [s for _, s in summary_rows]
        total_ok = all_statuses.count("ok")
        total_warn = all_statuses.count("warning")
        total_crit = all_statuses.count("critical")
        total_err = all_statuses.count("error")
        total_skipped = all_statuses.count("skipped")
        parts = []
        if total_ok:
            parts.append(f"{total_ok} passed")
        if total_warn:
            parts.append(f"{total_warn} warnings")
        if total_crit:
            parts.append(f"{total_crit} critical")
        if total_err:
            parts.append(f"{total_err} errors")
        if total_skipped:
            parts.append(f"{total_skipped} skipped")
        if parts:
            click.echo(f"\n  {', '.join(parts)}")

    # ===== Warning tier details =====
    for r in warning_results:
        status = _effective_status(r)
        if status == "ok":
            continue
        # Skipped checks carry remediation text in `message` (e.g. "Grant
        # pg_read_all_stats to this role"). Skip the items loop but still
        # print the message below.

        items_to_show = r["items"] if show_all else _actionable_items(r)
        if status != "skipped" and items_to_show:
            click.echo()
            click.secho(f"  {r['label']}", bold=True)
            for item in items_to_show:
                detail_head, detail_body = _detail_header_and_body(
                    item["detail"], body_indent=6
                )
                if item["table"]:
                    line = f"    {item['name']} on {item['table']} ({detail_head})"
                else:
                    line = f"    {item['name']} ({detail_head})"

                if item["source"] == "package":
                    click.secho(line, dim=True)
                    if detail_body:
                        click.secho(detail_body, dim=True)
                    click.secho(
                        f"      {item['package']} package — not your code",
                        dim=True,
                    )
                else:
                    if item["source"] == "app" and item["package"]:
                        click.echo(f"{line}  [{item['package']}]")
                    else:
                        click.echo(line)
                    if detail_body:
                        click.echo(detail_body)
                    click.secho(f"      {item['suggestion']}", dim=True)
                    for caveat in item["caveats"]:
                        click.secho(f"      caveat: {caveat}", dim=True, fg="yellow")

        if r["message"]:
            click.echo()
            click.secho(f"  {r['label']}: {r['message']}", bold=True)

    # ===== Operational tier — DB-state facts =====
    # Shown as context rather than alarms. Suggestions still visible so users
    # who want to act can, but the "fix" is DB-side (ANALYZE/VACUUM/REINDEX)
    # and isn't expressible in Plain code today. Build the full rows-to-render
    # list before deciding whether to print the section header — otherwise the
    # header can appear alone when every item is package-owned and --all is off.
    operational_rows: list[tuple[CheckResult, list[CheckItem]]] = []
    for r in operational_results:
        items_to_show = r["items"] if show_all else _actionable_items(r)
        has_status_message = r["status"] in ("skipped", "error") or r["message"]
        if items_to_show or has_status_message:
            operational_rows.append((r, items_to_show))

    if operational_rows:
        click.echo()
        click.secho(
            "  Operational context (DB-state, not code-fixable today)",
            bold=True,
            dim=True,
        )
        for r, items_to_show in operational_rows:
            click.secho(f"    {r['label']}: {r['summary']}", dim=True)
            # Print message whenever set, not only when items are empty — a
            # future check may want to add overall context alongside findings.
            if r["message"]:
                click.secho(f"      {r['message']}", dim=True)
            for item in items_to_show:
                detail_head, detail_body = _detail_header_and_body(
                    item["detail"], body_indent=8
                )
                if item["table"]:
                    line = f"      {item['name']} on {item['table']}"
                else:
                    line = f"      {item['name']}"
                click.secho(f"{line} — {detail_head}", dim=True)
                if detail_body:
                    click.secho(detail_body, dim=True)
                click.secho(f"        {item['suggestion']}", dim=True)
                for caveat in item["caveats"]:
                    click.secho(f"        caveat: {caveat}", dim=True, fg="yellow")

    # Package issues footnote (only when not --all)
    all_package_items: list[tuple[str, CheckItem]] = []
    if not show_all:
        for r in results:
            for item in _package_items(r):
                all_package_items.append((r["label"], item))

    if all_package_items:
        click.echo()
        # Group by package
        by_package: dict[str, list[tuple[str, CheckItem]]] = {}
        for check_label, item in all_package_items:
            by_package.setdefault(item["package"], []).append((check_label, item))

        pkg_parts = []
        for pkg, items in sorted(by_package.items()):
            check_names = sorted({label.lower() for label, _ in items})
            pkg_parts.append(f"{pkg} ({len(items)} — {', '.join(check_names)})")

        click.secho(
            f"  Also found {len(all_package_items)} issues in installed packages: {'; '.join(pkg_parts)}",
            dim=True,
        )

    # Slow queries
    slow_queries = context.get("slow_queries", [])
    if slow_queries:
        click.echo()
        click.secho("  Slowest queries (by total time)", bold=True)
        for q in slow_queries:
            click.echo(
                f"    {q['total_time_ms']:>10.0f}ms total"
                f"  {q['mean_time_ms']:>8.0f}ms avg"
                f"  {q['calls']:>8,} calls"
                f"  ({q['pct_total_time']:.1f}%)"
            )
            query_preview = q["query"].replace("\n", " ").strip()
            click.secho(f"      {query_preview}", dim=True)

    # Informationals — context numbers/strings, never warn
    informationals = context.get("informationals", [])
    if informationals:
        click.echo()
        click.secho("  Context", bold=True)
        label_w = max(len(i["label"]) for i in informationals)
        for info in informationals:
            value = info["value"]
            unit = info["unit"]
            if value is None:
                value_str = "never"
            elif unit:
                value_str = (
                    f"{value}{unit}" if unit.startswith("%") else f"{value} {unit}"
                )
            else:
                value_str = str(value)
            click.secho(
                f"    {info['label'].ljust(label_w)}  {value_str}",
                dim=True,
            )
            if info["note"]:
                click.secho(
                    f"    {' ' * label_w}  {info['note']}",
                    dim=True,
                )

    click.echo()


@click.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option(
    "--all", "show_all", is_flag=True, help="Include package issues in detail"
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Expand summary to show every check (passing and failing)",
)
@database_management_command
def diagnose(output_json: bool, show_all: bool, verbose: bool) -> None:
    """Run health checks against the database"""
    conn = get_connection()
    table_owners = build_table_owners()

    with conn.cursor() as cursor:
        results, context = run_all_checks(cursor, table_owners)

    if output_json:
        output = {
            "checks": results,
            "context": context,
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        format_human(results, context, show_all=show_all, verbose=verbose)

    # Exit 1 if any critical (JSON mode always exits 0 — the data is the signal)
    if not output_json and any(r["status"] == "critical" for r in results):
        sys.exit(1)
