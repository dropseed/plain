from __future__ import annotations

import json
import sys
from typing import Any

import click

from ..db import get_connection
from ..introspection import CheckItem, CheckResult, build_table_owners, run_all_checks
from .decorators import database_management_command

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
) -> None:
    # Split items into actionable (app + unmanaged) vs package
    def _actionable_items(r: CheckResult) -> list[CheckItem]:
        return [i for i in r["items"] if i["source"] != "package"]

    def _package_items(r: CheckResult) -> list[CheckItem]:
        return [i for i in r["items"] if i["source"] == "package"]

    # Compute effective status (only actionable items trigger warnings unless --all)
    def _effective_status(r: CheckResult) -> str:
        if show_all:
            return r["status"]
        if r["status"] in ("ok", "skipped", "error"):
            return r["status"]
        if r["items"] and not _actionable_items(r):
            return "ok"
        return r["status"]

    # Summary table
    label_width = max(len(r["label"]) for r in results)
    summaries: list[str] = []
    for r in results:
        if _effective_status(r) == r["status"]:
            summaries.append(r["summary"])
        else:
            summaries.append("ok")
    summary_width = max(len(s) for s in summaries)

    click.echo()
    for r, summary_text in zip(results, summaries):
        status = _effective_status(r)
        symbol, color = STATUS_SYMBOLS.get(status, ("?", None))
        label = r["label"].ljust(label_width)
        summary = summary_text.ljust(summary_width)
        click.echo(f"  {label}  {summary}  ", nl=False)
        click.secho(symbol, fg=color)

    # Counts
    statuses = [_effective_status(r) for r in results]
    ok_count = statuses.count("ok")
    warn_count = statuses.count("warning")
    critical_count = statuses.count("critical")
    error_count = statuses.count("error")

    parts = []
    if ok_count:
        parts.append(f"{ok_count} passed")
    if warn_count:
        parts.append(f"{warn_count} warnings")
    if critical_count:
        parts.append(f"{critical_count} critical")
    if error_count:
        parts.append(f"{error_count} errors")
    click.echo(f"\n  {', '.join(parts)}")

    # Details
    for r in results:
        if _effective_status(r) in ("ok", "skipped"):
            continue

        items_to_show = r["items"] if show_all else _actionable_items(r)
        if items_to_show:
            click.echo()
            click.secho(f"  {r['label']}", bold=True)
            for item in items_to_show:
                if item["table"]:
                    line = f"    {item['name']} on {item['table']} ({item['detail']})"
                else:
                    line = f"    {item['name']} ({item['detail']})"

                if item["source"] == "package":
                    click.secho(line, dim=True)
                    click.secho(
                        f"      {item['package']} package — not your code",
                        dim=True,
                    )
                else:
                    if item["source"] == "app" and item["package"]:
                        click.echo(f"{line}  [{item['package']}]")
                    else:
                        click.echo(line)
                    click.secho(f"      {item['suggestion']}", dim=True)

        if r["message"]:
            click.echo()
            click.secho(f"  {r['label']}: {r['message']}", bold=True)

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

    # Footer
    click.echo()
    stats_reset = context.get("stats_reset")
    click.secho(
        f"  Stats reset: {stats_reset[:10] if stats_reset else 'never'}",
        dim=True,
    )

    pgss = context.get("pg_stat_statements")
    if pgss == "not_installed":
        click.secho(
            "  pg_stat_statements: not installed (install for query analysis)",
            dim=True,
        )
    elif pgss == "no_permission":
        click.secho(
            "  pg_stat_statements: installed but not accessible (insufficient privileges)",
            dim=True,
        )

    conn = context.get("connections", {})
    if conn:
        pct = round(100 * conn["active"] / conn["max"]) if conn["max"] else 0
        click.secho(f"  Connections: {conn['active']}/{conn['max']} ({pct}%)", dim=True)

    click.echo()


@click.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option(
    "--all", "show_all", is_flag=True, help="Include package issues in detail"
)
@database_management_command
def diagnose(output_json: bool, show_all: bool) -> None:
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
        format_human(results, context, show_all=show_all)

    # Exit 1 if any critical (JSON mode always exits 0 — the data is the signal)
    if not output_json and any(r["status"] == "critical" for r in results):
        sys.exit(1)
