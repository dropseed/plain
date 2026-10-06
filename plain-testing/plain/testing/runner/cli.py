from plain.cli.runtime import common_command

from .main import main

__all__ = []

# `plain test` is the runner's own command, options and all, so `--help`
# lists what it takes.
#
# It is contributed through the `plain.cli` entry point group, which runs
# before `plain.runtime.setup()` — so the runner still owns the setup decision
# (app mode vs library mode) and calls setup() itself.
cli = common_command(main)
