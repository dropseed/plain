import importlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path

import click
from click.core import Command, Context

import plain.runtime
from plain import preflight
from plain.assets.compile import compile_assets, get_compiled_path
from plain.exceptions import ImproperlyConfigured
from plain.packages import packages
from plain.utils.crypto import get_random_string

from .formatting import PlainContext
from .packages import EntryPointGroup, InstalledPackagesGroup


@click.group()
def plain_cli():
    pass


# @plain_cli.command
# def docs():
#     """Open the Forge documentation in your browser"""
#     subprocess.run(["open", "https://www.forgepackages.com/docs/?ref=cli"])


@plain_cli.command()
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


@plain_cli.command()
@click.argument("script", nargs=1, type=click.Path(exists=True))
def run(script):
    """Run a Python script in the context of your app"""
    before_script = "import plain.runtime; plain.runtime.setup()"
    command = f"{before_script}; exec(open('{script}').read())"
    result = subprocess.run(["python", "-c", command])
    if result.returncode:
        sys.exit(result.returncode)


# @plain_cli.command()
# @click.option("--filter", "-f", "name_filter", help="Filter settings by name")
# @click.option("--overridden", is_flag=True, help="Only show overridden settings")
# def settings(name_filter, overridden):
#     """Print Plain settings"""
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


@plain_cli.command("preflight")
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
            click.secho("✔ Preflight check identified no issues.", err=True, fg="green")


@plain_cli.command()
@click.option(
    "--keep-original/--no-keep-original",
    "keep_original",
    is_flag=True,
    default=False,
    help="Keep the original assets",
)
@click.option(
    "--fingerprint/--no-fingerprint",
    "fingerprint",
    is_flag=True,
    default=True,
    help="Fingerprint the assets",
)
@click.option(
    "--compress/--no-compress",
    "compress",
    is_flag=True,
    default=True,
    help="Compress the assets",
)
def compile(keep_original, fingerprint, compress):
    """Compile static assets"""

    if not keep_original and not fingerprint:
        click.secho(
            "You must either keep the original assets or fingerprint them.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    for entry_point in entry_points(group="plain.assets.compile"):
        click.secho(f"Running {entry_point.name}", bold=True)
        result = entry_point.load()()
        print()

    # TODO also look in [tool.plain.compile.run]

    # Run a "compile" script from package.json automatically
    package_json = Path("package.json")
    if package_json.exists():
        with package_json.open() as f:
            package = json.load(f)

        if package.get("scripts", {}).get("compile"):
            click.secho("Running `npm run compile`", bold=True)
            result = subprocess.run(["npm", "run", "compile"])
            print()
            if result.returncode:
                click.secho(
                    f"Error in `npm run compile` (exit {result.returncode})", fg="red"
                )
                sys.exit(result.returncode)

    # Compile our assets
    target_dir = get_compiled_path()
    click.secho(f"Compiling assets to {target_dir}", bold=True)
    if target_dir.exists():
        click.secho("(clearing previously compiled assets)")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    total_compiled = 0

    for url_path, resolved_url_path, compiled_paths in compile_assets(
        target_dir=target_dir,
        keep_original=keep_original,
        fingerprint=fingerprint,
        compress=compress,
    ):
        if url_path == resolved_url_path:
            click.secho(url_path, bold=True)
        else:
            click.secho(url_path, bold=True, nl=False)
            click.secho(" → ", fg="yellow", nl=False)
            click.echo(resolved_url_path)

        print("\n".join(f"  {Path(p).relative_to(Path.cwd())}" for p in compiled_paths))

        total_files += 1
        total_compiled += len(compiled_paths)

    click.secho(
        f"\nCompiled {total_files} assets into {total_compiled} files", fg="green"
    )


@plain_cli.command()
@click.argument("package_name")
def create(package_name):
    """
    Create a new local package.

    The PACKAGE_NAME is typically a plural noun, like "users" or "posts",
    where you might create a "User" or "Post" model inside of the package.
    """
    package_dir = plain.runtime.APP_PATH / package_name
    package_dir.mkdir(exist_ok=True)

    empty_dirs = (
        f"templates/{package_name}",
        "migrations",
    )
    for d in empty_dirs:
        (package_dir / d).mkdir(parents=True, exist_ok=True)

    empty_files = (
        "__init__.py",
        "migrations/__init__.py",
        "models.py",
        "views.py",
    )
    for f in empty_files:
        (package_dir / f).touch(exist_ok=True)

    # Create a urls.py file with a default namespace
    if not (package_dir / "urls.py").exists():
        (package_dir / "urls.py").write_text(
            f"""from plain.urls import path

default_namespace = f"{package_name}"

urlpatterns = [
    # path("", views.IndexView, name="index"),
]
"""
        )

    click.secho(
        f'Created {package_dir.relative_to(Path.cwd())}. Make sure to add "{package_name}" to INSTALLED_PACKAGES!',
        fg="green",
    )


@plain_cli.command()
@click.argument("setting_name")
def setting(setting_name):
    """Print the value of a setting at runtime"""
    try:
        setting = getattr(plain.runtime.settings, setting_name)
        click.echo(setting)
    except AttributeError:
        click.secho(f'Setting "{setting_name}" not found', fg="red")


@plain_cli.group()
def utils():
    pass


@utils.command()
def generate_secret_key():
    """Generate a new secret key"""
    new_secret_key = get_random_string(50)
    click.echo(new_secret_key)


class AppCLIGroup(click.Group):
    """
    Loads app.cli if it exists as `plain app`
    """

    MODULE_NAME = "app.cli"

    def list_commands(self, ctx):
        try:
            find_spec(self.MODULE_NAME)
            return ["app"]
        except ModuleNotFoundError:
            return []

    def get_command(self, ctx, name):
        if name != "app":
            return

        try:
            cli = importlib.import_module(self.MODULE_NAME)
            return cli.cli
        except ModuleNotFoundError:
            return


class PlainCommandCollection(click.CommandCollection):
    context_class = PlainContext

    def __init__(self, *args, **kwargs):
        sources = []

        try:
            # Setup has to run before the installed packages CLI work
            # and it also does the .env file loading right now...
            plain.runtime.setup()

            sources = [
                InstalledPackagesGroup(),
                EntryPointGroup(),
                AppCLIGroup(),
                plain_cli,
            ]
        except plain.runtime.AppPathNotFound:
            click.secho(
                "Plain `app` directory not found. Some commands may be missing.",
                fg="yellow",
                err=True,
            )

            sources = [
                EntryPointGroup(),
                plain_cli,
            ]
        except ImproperlyConfigured as e:
            click.secho(
                str(e),
                fg="red",
                err=True,
            )

            # None of these require the app to be setup
            sources = [
                EntryPointGroup(),
                AppCLIGroup(),
                plain_cli,
            ]
        except Exception as e:
            print("---")
            print(traceback.format_exc())
            print("---")

            click.secho(
                f"Error: {e}",
                fg="red",
                err=True,
            )

            # None of these require the app to be setup
            sources = [
                EntryPointGroup(),
                AppCLIGroup(),
                plain_cli,
            ]

        super().__init__(*args, **kwargs)

        self.sources = sources

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd:
            # Pass the formatting down to subcommands automatically
            cmd.context_class = self.context_class
        return cmd


cli = PlainCommandCollection()
