import json
import sys

import click

from plain import preflight
from plain.packages import packages_registry
from plain.preflight.registry import checks_registry
from plain.runtime import settings


@click.group("preflight")
def preflight_cli():
    """Run or manage preflight checks."""
    pass


@preflight_cli.command("check")
@click.option(
    "--deploy",
    is_flag=True,
    help="Check deployment settings.",
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
def check_command(deploy, format, quiet):
    """
    Use the system check framework to validate entire Plain project.
    Exit with error code if any errors are found. Warnings do not cause failure.
    """
    # Auto-discover and load preflight checks
    packages_registry.autodiscover_modules("preflight", include_app=True)

    if not quiet:
        click.secho("Running preflight checks...", dim=True, italic=True, err=True)

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
                click.echo("Check:", nl=False, err=True)
                click.secho(f"{check_name} ", bold=True, nl=False, err=True)

            # Determine status icon based on issue severity
            if not visible_issues:
                # No issues - passed
                if not quiet:
                    click.secho("✔", fg="green", err=True)
                passed_checks += 1
            else:
                # Has issues - determine icon based on highest severity
                has_errors = any(not issue.warning for issue in visible_issues)
                if not quiet:
                    if has_errors:
                        click.secho("✗", fg="red", err=True)
                    else:
                        click.secho("⚠", fg="yellow", err=True)

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
                            click.secho(f"{check_name}:", err=True)
                        # Show ID and fix on separate lines with same indentation
                        click.secho(
                            f"  [{issue_type}] {issue.id}:",
                            fg=issue_color,
                            bold=True,
                            err=True,
                            nl=False,
                        )
                        click.secho(f" {issue.fix}", err=True, dim=True)
                    else:
                        # Show ID and fix on separate lines with same indentation
                        click.secho(
                            f"    [{issue_type}] {issue.id}: ",
                            fg=issue_color,
                            bold=True,
                            err=True,
                            nl=False,
                        )
                        click.secho(f"{issue.fix}", err=True, dim=True)
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
        results = {"passed": not has_errors, "checks": []}

        for check_class, check_name, issues in check_results:
            visible_issues = [issue for issue in issues if not issue.is_silenced()]

            check_result = {
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

        click.secho(f"{icon}{summary_text}", fg=summary_color, err=True)

    # Exit with error if there are any errors (not warnings)
    if has_errors:
        sys.exit(1)


@preflight_cli.command("list")
def list_checks():
    """List all available preflight checks."""
    packages_registry.autodiscover_modules("preflight", include_app=True)

    regular = []
    deployment = []
    silenced_checks = settings.PREFLIGHT_SILENCED_CHECKS

    for name, (check_class, deploy) in sorted(checks_registry.checks.items()):
        # Use class docstring as description
        description = check_class.__doc__ or "No description"
        # Get first line of docstring
        description = description.strip().split("\n")[0]

        is_silenced = name in silenced_checks
        if deploy:
            deployment.append((name, description, is_silenced))
        else:
            regular.append((name, description, is_silenced))

    if regular:
        click.echo("Regular checks:")
        for name, description, is_silenced in regular:
            silenced_text = (
                click.style(" (silenced)", fg="red", dim=True) if is_silenced else ""
            )
            click.echo(
                f"  {click.style(name)}: {click.style(description, dim=True)}{silenced_text}"
            )

    if deployment:
        click.echo("\nDeployment checks:")
        for name, description, is_silenced in deployment:
            silenced_text = (
                click.style(" (silenced)", fg="red", dim=True) if is_silenced else ""
            )
            click.echo(
                f"  {click.style(name)}: {click.style(description, dim=True)}{silenced_text}"
            )

    if not regular and not deployment:
        click.echo("No preflight checks found.")
