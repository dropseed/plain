import os

import click
from plain.cli.runtime import common_command


@common_command
@click.command(
    context_settings={
        "ignore_unknown_options": True,
    }
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli(args: tuple[str, ...]) -> None:
    """Run tests"""
    # This command is contributed through the `plain.cli` entry point group,
    # which runs before `plain.runtime.setup()` — so the runner still owns the
    # setup decision (app mode vs library mode) and can call setup() itself.
    os.environ.setdefault("PLAIN_ENV", "test")

    from .main import main

    main.main(args=list(args), prog_name="plain test")
