from __future__ import annotations

import os
import subprocess
import sys

import click

from plain.cli.runtime import common_command


@common_command
@click.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
@click.option(
    "-c",
    "--command",
    help="Execute the given command and exit.",
)
def shell(interface: str | None, command: str | None) -> None:
    """Interactive Python shell"""

    if command:
        # Execute the command and exit
        before_script = "import plain.runtime; plain.runtime.setup()"
        full_command = f"{before_script}; {command}"
        result = subprocess.run(["python", "-c", full_command])
        if result.returncode:
            sys.exit(result.returncode)
        return

    interface_list: list[str]
    if interface:
        interface_list = [interface]
    else:

        def get_default_interface() -> list[str]:
            try:
                import IPython  # noqa: F401  # type: ignore[import-not-found]

                return ["python", "-m", "IPython"]
            except ImportError:
                pass

            return ["python"]

        interface_list = get_default_interface()

    result = subprocess.run(
        interface_list,
        env={
            "PYTHONSTARTUP": os.path.join(os.path.dirname(__file__), "startup.py"),
            **os.environ,
        },
    )
    if result.returncode:
        sys.exit(result.returncode)


@click.command()
@click.argument("script", nargs=1, type=click.Path(exists=True))
def run(script: str) -> None:
    """Execute Python scripts with app context"""
    before_script = "import plain.runtime; plain.runtime.setup()"
    command = f"{before_script}; exec(open('{script}').read())"
    result = subprocess.run(["python", "-c", command])
    if result.returncode:
        sys.exit(result.returncode)
