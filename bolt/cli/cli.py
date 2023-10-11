import os
import subprocess
import sys
from importlib.util import find_spec

import click

import bolt.runtime
from bolt.env.cli import cli as env_cli

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
    # TODO make this an entrypoint instead
    if find_spec("bolt.tailwind") is not None:
        result = subprocess.run(["bolt", "tailwind", "compile", "--minify"])
        if result.returncode:
            click.secho(
                f"Error compiling Tailwind CSS (exit {result.returncode})", fg="red"
            )
            sys.exit(result.returncode)

    # TODO also look in [tool.bolt.compile.run]

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
