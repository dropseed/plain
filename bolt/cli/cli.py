import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import click

import bolt.runtime
from bolt import preflight
from bolt.env.cli import cli as env_cli
from bolt.packages import packages

from .packages import EntryPointGroup, InstalledPackagesGroup


@click.group()
def bolt_cli():
    pass


@bolt_cli.command(
    "legacy",
    context_settings={
        "ignore_unknown_options": True,
    },
)
@click.argument("legacy_args", nargs=-1, type=click.UNPROCESSED)
def legacy_alias(legacy_args):
    result = subprocess.run(
        [
            "python",
            "-m",
            "bolt.legacy",
            *legacy_args,
        ],
    )
    if result.returncode:
        sys.exit(result.returncode)


# @bolt_cli.command
# def docs():
#     """Open the Forge documentation in your browser"""
#     subprocess.run(["open", "https://www.forgepackages.com/docs/?ref=cli"])


@bolt_cli.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
def shell(interface):
    """
    Runs a Python interactive interpreter. Tries to use IPython or
    bpython, if one of them is available.
    """

    if interface:
        interface = [interface]
    else:

        def get_default_interface():
            try:
                import IPython  # noqa

                return ["python", "-m", "IPython"]
            except ImportError:
                pass

            return ["python"]

        interface = get_default_interface()

    result = subprocess.run(
        interface,
        env={
            "PYTHONSTARTUP": os.path.join(os.path.dirname(__file__), "startup.py"),
            **os.environ,
        },
    )
    if result.returncode:
        sys.exit(result.returncode)


@bolt_cli.command()
@click.argument("script", nargs=1, type=click.Path(exists=True))
def run(script):
    """Run a Python script in the context of your app"""
    before_script = "import bolt.runtime; bolt.runtime.setup()"
    command = f"{before_script}; exec(open('{script}').read())"
    result = subprocess.run(["python", "-c", command])
    if result.returncode:
        sys.exit(result.returncode)


# @bolt_cli.command()
# @click.option("--filter", "-f", "name_filter", help="Filter settings by name")
# @click.option("--overridden", is_flag=True, help="Only show overridden settings")
# def settings(name_filter, overridden):
#     """Print Bolt settings"""
#     table = Table(box=box.MINIMAL)
#     table.add_column("Setting")
#     table.add_column("Default value")
#     table.add_column("App value")
#     table.add_column("Type")
#     table.add_column("Module")

#     for setting in dir(settings):
#         if setting.isupper():
#             if name_filter and name_filter.upper() not in setting:
#                 continue

#             is_overridden = settings.is_overridden(setting)

#             if overridden and not is_overridden:
#                 continue

#             default_setting = settings._default_settings.get(setting)
#             if default_setting:
#                 default_value = default_setting.value
#                 annotation = default_setting.annotation
#                 module = default_setting.module
#             else:
#                 default_value = ""
#                 annotation = ""
#                 module = ""

#             table.add_row(
#                 setting,
#                 Pretty(default_value) if default_value else "",
#                 Pretty(getattr(settings, setting))
#                 if is_overridden
#                 else Text("<Default>", style="italic dim"),
#                 Pretty(annotation) if annotation else "",
#                 str(module.__name__) if module else "",
#             )

#     console = Console()
#     console.print(table)


@bolt_cli.command("preflight")
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
    Use the system check framework to validate entire Bolt project.
    Raise CommandError for any serious message (error or critical errors).
    If there are only light messages (like warnings), print them to stderr
    and don't raise an exception.
    """
    include_deployment_checks = deploy

    if package_label:
        package_configs = [
            packages.get_package_config(label) for label in package_label
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
            else "%s issues" % visible_issue_count,
            len(all_issues) - visible_issue_count,
        )
        msg = click.style("SystemCheckError: %s" % header, fg="red") + body + footer
        raise click.ClickException(msg)
    else:
        if visible_issue_count:
            footer += "\n"
            footer += "Preflight check identified {} ({} silenced).".format(
                "no issues"
                if visible_issue_count == 0
                else "1 issue"
                if visible_issue_count == 1
                else "%s issues" % visible_issue_count,
                len(all_issues) - visible_issue_count,
            )
            msg = header + body + footer
            click.echo(msg, err=True)
        else:
            click.echo("Preflight check identified no issues.", err=True)


@bolt_cli.command()
@click.pass_context
def compile(ctx):
    """Compile static assets"""

    # TODO preflight for assets only?

    # TODO make this an entrypoint instead
    # Compile our Tailwind CSS (including templates in bolt itself)
    if find_spec("bolt.tailwind") is not None:
        result = subprocess.run(["bolt", "tailwind", "compile", "--minify"])
        if result.returncode:
            click.secho(
                f"Error compiling Tailwind CSS (exit {result.returncode})", fg="red"
            )
            sys.exit(result.returncode)

    # TODO also look in [tool.bolt.compile.run]

    # Run a "compile" script from package.json automatically
    package_json = Path("package.json")
    if package_json.exists():
        with package_json.open() as f:
            package = json.load(f)

        if package.get("scripts", {}).get("compile"):
            result = subprocess.run(["npm", "run", "compile"])
            if result.returncode:
                click.secho(
                    f"Error in `npm run compile` (exit {result.returncode})", fg="red"
                )
                sys.exit(result.returncode)

    # Run the regular collectstatic
    ctx.invoke(legacy_alias, legacy_args=["collectstatic", "--noinput"])


# Add other internal packages that don't need to be in INSTALLED_PACKAGES
bolt_cli.add_command(env_cli)


class BoltCommandCollection(click.CommandCollection):
    def __init__(self, *args, **kwargs):
        bolt.runtime.setup()

        super().__init__(*args, **kwargs)

        self.sources = [
            InstalledPackagesGroup(),
            EntryPointGroup(),
            bolt_cli,
        ]


cli = BoltCommandCollection()
