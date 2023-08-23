import importlib
import os
import re
import subprocess
import sys

import click
from rich import box
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table
from rich.text import Text

import bolt.runtime
from bolt.apps import apps


class InstalledAppsGroup(click.Group):
    BOLT_APPS_PREFIX = "bolt."

    def list_commands(self, ctx):
        try:
            bolt.runtime.setup()
        except Exception as e:
            click.secho(f"Error in bolt.runtime.setup()\n{e}", fg="yellow")
            return []

        apps_with_commands = []

        # Get installed apps with a cli.py module
        for app in apps.get_app_configs():
            cli_module = app.name + ".cli"
            try:
                importlib.import_module(cli_module)
            except ModuleNotFoundError:
                continue

            cli_name = app.name

            if cli_name.startswith(self.BOLT_APPS_PREFIX):
                cli_name = cli_name[len(self.BOLT_APPS_PREFIX) :]

            apps_with_commands.append(cli_name)

        return apps_with_commands

    def get_command(self, ctx, name):
        # Try it as bolt.x and just x (we don't know ahead of time which it is, but prefer bolt.x)
        for name in [self.BOLT_APPS_PREFIX + name, name]:
            try:
                cli = importlib.import_module(name + ".cli")
            except ModuleNotFoundError:
                return

            # Get the app's cli.py group
            try:
                return cli.cli
            except AttributeError:
                return


class BinNamespaceGroup(click.Group):
    COMMAND_PREFIX = "bolt-"

    def list_commands(self, ctx):
        bin_dir = os.path.dirname(sys.executable)
        rv = []
        for filename in os.listdir(bin_dir):
            if filename.startswith(self.COMMAND_PREFIX):
                rv.append(filename[len(self.COMMAND_PREFIX) :])

        rv.sort()
        return rv

    def get_command(self, ctx, name):
        # Remove hyphens and prepend w/ "bolt"
        # so "pre-commit" becomes "forgeprecommit" as an import
        imported = self.import_module_cli("bolt." + name.replace("-", ""))
        if imported:
            return imported

        # Re-create the bin path and make sure it exists
        bin_path = os.path.join(
            os.path.dirname(sys.executable), self.COMMAND_PREFIX + name
        )
        if not os.path.exists(bin_path):
            return

        # Support multiple CLIs that came from the same package
        # by looking at the contents of the bin command itself
        with open(bin_path) as f:
            for line in f:
                if "from bolt." in line and "from bolt.cli" not in line:
                    module = re.search(r"from (bolt\.([\w\.]+))", line).group(1)
                    if module:
                        imported = self.import_module_cli(module)
                        if imported:
                            return imported

    def import_module_cli(self, name):
        try:
            i = importlib.import_module(name)
            return i.cli
        except (ImportError, AttributeError):
            pass


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


@bolt_cli.command()
@click.option("--filter", "-f", "name_filter", help="Filter settings by name")
@click.option("--overridden", is_flag=True, help="Only show overridden settings")
def settings(name_filter, overridden):
    """Print Bolt settings"""
    try:
        bolt.runtime.setup()
    except Exception as e:
        click.secho(f"Error in bolt.runtime.setup()\n{e}", fg="yellow")
        return

    from bolt.runtime import settings

    table = Table(box=box.MINIMAL)
    table.add_column("Setting")
    table.add_column("Default value")
    table.add_column("App value")
    table.add_column("Type")
    table.add_column("Module")

    for setting in dir(settings):
        if setting.isupper():
            if name_filter and name_filter.upper() not in setting:
                continue

            is_overridden = settings.is_overridden(setting)

            if overridden and not is_overridden:
                continue

            default_setting = settings._default_settings.get(setting)
            if default_setting:
                default_value = default_setting.value
                annotation = default_setting.annotation
                module = default_setting.module
            else:
                default_value = ""
                annotation = ""
                module = ""

            table.add_row(
                setting,
                Pretty(default_value) if default_value else "",
                Pretty(getattr(settings, setting))
                if is_overridden
                else Text("<Default>", style="italic dim"),
                Pretty(annotation) if annotation else "",
                str(module.__name__) if module else "",
            )

    console = Console()
    console.print(table)


@bolt_cli.command()
@click.pass_context
def compile(ctx):
    """Compile static assets"""
    # For each installed app, if it has a compile command, run it?
    # So this could be `bolt compile`
    # and you have `bolt tailwind compile`
    # and `bolt static compile`

    # maybe also user customization in pyproject.toml (like bolt work)

    # Compile our Tailwind CSS (including templates in bolt itself)
    # TODO not necessarily installed
    result = subprocess.run(["bolt", "tailwind", "compile", "--minify"])
    if result.returncode:
        click.secho(
            f"Error compiling Tailwind CSS (exit {result.returncode})", fg="red"
        )
        sys.exit(result.returncode)

    # Run the regular collectstatic
    ctx.invoke(legacy_alias, legacy_args=["collectstatic", "--noinput"])


cli = click.CommandCollection(
    sources=[InstalledAppsGroup(), BinNamespaceGroup(), bolt_cli]
)
