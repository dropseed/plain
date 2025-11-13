import json
import sys
from typing import Any

import click

from plain import preflight
from plain.cli.runtime import common_command
from plain.packages import packages_registry


@common_command
@click.command("preflight")
@click.option(
    "--deploy",
    is_flag=True,
    help="Include deployment checks.",
)
@click.option(
    "--format",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format (default: text)",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Hide progress output and warnings, only show errors.",
)
def preflight_cli(deploy: bool, format: str, quiet: bool) -> None:
    """Validation checks before deployment"""
    # Use stderr for progress messages only in JSON mode (keeps stdout clean for parsing)
    # In text mode, send all output to stdout (so success doesn't appear in error logs)
    use_stderr = format == "json"

    # Auto-discover and load preflight checks
    packages_registry.autodiscover_modules("preflight", include_app=True)
    if not quiet:
        click.secho(
            "Running preflight checks...", dim=True, italic=True, err=use_stderr
        )

    total_checks = 0
    passed_checks = 0
    check_results = []

    # Run checks and collect results
    for check_class, check_name, issues in preflight.run_checks(
        include_deploy_checks=deploy,
    ):
        total_checks += 1

        # Filter out silenced issues
        visible_issues = [issue for issue in issues if not issue.is_silenced()]

        # For text format, show real-time progress
        if format == "text":
            if not quiet:
                # Print check name without newline
                click.echo("Check:", nl=False, err=use_stderr)
                click.secho(f"{check_name} ", bold=True, nl=False, err=use_stderr)

            # Determine status icon based on issue severity
            if not visible_issues:
                # No issues - passed
                if not quiet:
                    click.secho("✔", fg="green", err=use_stderr)
                passed_checks += 1
            else:
                # Has issues - determine icon based on highest severity
                has_errors = any(not issue.warning for issue in visible_issues)
                if not quiet:
                    if has_errors:
                        click.secho("✗", fg="red", err=use_stderr)
                    else:
                        click.secho("⚠", fg="yellow", err=use_stderr)

                # Print issues with simple indentation
                issues_to_show = (
                    visible_issues
                    if not quiet
                    else [issue for issue in visible_issues if not issue.warning]
                )
                for i, issue in enumerate(issues_to_show):
                    issue_color = "red" if not issue.warning else "yellow"
                    issue_type = "ERROR" if not issue.warning else "WARNING"

                    if quiet:
                        # In quiet mode, show check name once, then issues
                        if i == 0:
                            click.secho(f"{check_name}:", err=use_stderr)
                        # Show ID and fix on separate lines with same indentation
                        click.secho(
                            f"  [{issue_type}] {issue.id}:",
                            fg=issue_color,
                            bold=True,
                            err=use_stderr,
                            nl=False,
                        )
                        click.secho(f" {issue.fix}", err=use_stderr, dim=True)
                    else:
                        # Show ID and fix on separate lines with same indentation
                        click.secho(
                            f"    [{issue_type}] {issue.id}: ",
                            fg=issue_color,
                            bold=True,
                            err=use_stderr,
                            nl=False,
                        )
                        click.secho(f"{issue.fix}", err=use_stderr, dim=True)
        else:
            # For JSON format, just count passed checks
            if not visible_issues:
                passed_checks += 1

        check_results.append((check_class, check_name, issues))

    # Output results based on format

    # Get all issues from check_results instead of maintaining separate list
    all_issues = [issue for _, _, issues in check_results for issue in issues]
    # Errors (non-warnings) cause preflight to fail
    has_errors = any(
        not issue.warning and not issue.is_silenced() for issue in all_issues
    )

    if format == "json":
        # Build JSON output
        results: dict[str, Any] = {"passed": not has_errors, "checks": []}

        for check_class, check_name, issues in check_results:
            visible_issues = [issue for issue in issues if not issue.is_silenced()]

            check_result: dict[str, Any] = {
                "name": check_name,
                "passed": len(visible_issues) == 0,
                "issues": [],
            }

            for issue in visible_issues:
                issue_data = {
                    "id": issue.id,
                    "warning": issue.warning,
                    "fix": issue.fix,
                    "obj": str(issue.obj) if issue.obj is not None else None,
                }
                check_result["issues"].append(issue_data)

            results["checks"].append(check_result)

        click.echo(json.dumps(results, indent=2))
    else:
        # Text format summary
        if not quiet:
            click.echo()

        # Calculate warning and error counts
        warning_count = sum(
            1
            for _, _, issues in check_results
            if issues
            and not any(
                not issue.warning for issue in issues if not issue.is_silenced()
            )
        )
        error_count = sum(
            1
            for _, _, issues in check_results
            if issues
            and any(not issue.warning for issue in issues if not issue.is_silenced())
        )

        # Build colored summary parts
        summary_parts = []

        if passed_checks > 0:
            summary_parts.append(click.style(f"{passed_checks} passed", fg="green"))

        if warning_count > 0:
            summary_parts.append(click.style(f"{warning_count} warnings", fg="yellow"))

        if error_count > 0:
            summary_parts.append(click.style(f"{error_count} errors", fg="red"))

        # Show checkmark if successful (no errors)
        if not has_errors:
            icon = click.style("✔ ", fg="green")
            summary_color = "green"
        else:
            icon = ""
            summary_color = None

        summary_text = ", ".join(summary_parts) if summary_parts else "no issues"

        click.secho(f"{icon}{summary_text}", fg=summary_color, err=use_stderr)

    # Exit with error if there are any errors (not warnings)
    if has_errors:
        sys.exit(1)
