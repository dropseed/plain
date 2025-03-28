import click

from plain import preflight
from plain.packages import packages_registry


@click.command("preflight")
@click.argument("package_label", nargs=-1)
@click.option(
    "--deploy",
    is_flag=True,
    help="Check deployment settings.",
)
@click.option(
    "--fail-level",
    default="ERROR",
    type=click.Choice(["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]),
    help="Message level that will cause the command to exit with a non-zero status. Default is ERROR.",
)
@click.option(
    "--database",
    "databases",
    multiple=True,
    help="Run database related checks against these aliases.",
)
def preflight_checks(package_label, deploy, fail_level, databases):
    """
    Use the system check framework to validate entire Plain project.
    Raise CommandError for any serious message (error or critical errors).
    If there are only light messages (like warnings), print them to stderr
    and don't raise an exception.
    """
    include_deployment_checks = deploy

    if package_label:
        package_configs = [
            packages_registry.get_package_config(label) for label in package_label
        ]
    else:
        package_configs = None

    all_issues = preflight.run_checks(
        package_configs=package_configs,
        include_deployment_checks=include_deployment_checks,
        databases=databases,
    )

    header, body, footer = "", "", ""
    visible_issue_count = 0  # excludes silenced warnings

    if all_issues:
        debugs = [
            e for e in all_issues if e.level < preflight.INFO and not e.is_silenced()
        ]
        infos = [
            e
            for e in all_issues
            if preflight.INFO <= e.level < preflight.WARNING and not e.is_silenced()
        ]
        warnings = [
            e
            for e in all_issues
            if preflight.WARNING <= e.level < preflight.ERROR and not e.is_silenced()
        ]
        errors = [
            e
            for e in all_issues
            if preflight.ERROR <= e.level < preflight.CRITICAL and not e.is_silenced()
        ]
        criticals = [
            e
            for e in all_issues
            if preflight.CRITICAL <= e.level and not e.is_silenced()
        ]
        sorted_issues = [
            (criticals, "CRITICALS"),
            (errors, "ERRORS"),
            (warnings, "WARNINGS"),
            (infos, "INFOS"),
            (debugs, "DEBUGS"),
        ]

        for issues, group_name in sorted_issues:
            if issues:
                visible_issue_count += len(issues)
                formatted = (
                    click.style(str(e), fg="red")
                    if e.is_serious()
                    else click.style(str(e), fg="yellow")
                    for e in issues
                )
                formatted = "\n".join(sorted(formatted))
                body += f"\n{group_name}:\n{formatted}\n"

    if visible_issue_count:
        header = "Preflight check identified some issues:\n"

    if any(
        e.is_serious(getattr(preflight, fail_level)) and not e.is_silenced()
        for e in all_issues
    ):
        footer += "\n"
        footer += "Preflight check identified {} ({} silenced).".format(
            "no issues"
            if visible_issue_count == 0
            else "1 issue"
            if visible_issue_count == 1
            else f"{visible_issue_count} issues",
            len(all_issues) - visible_issue_count,
        )
        msg = click.style(f"SystemCheckError: {header}", fg="red") + body + footer
        raise click.ClickException(msg)
    else:
        if visible_issue_count:
            footer += "\n"
            footer += "Preflight check identified {} ({} silenced).".format(
                "no issues"
                if visible_issue_count == 0
                else "1 issue"
                if visible_issue_count == 1
                else f"{visible_issue_count} issues",
                len(all_issues) - visible_issue_count,
            )
            msg = header + body + footer
            click.echo(msg, err=True)
        else:
            click.secho("✔ Preflight check identified no issues.", err=True, fg="green")
