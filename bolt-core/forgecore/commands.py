import os
import sys

import click


class DjangoClickAliasCommand:
    click_command = None

    def run_from_argv(self, argv):
        self._called_from_command_line = True
        prog_name = "{} {}".format(os.path.basename(argv[0]), argv[1])
        try:
            # We won't get an exception here in standalone_mode=False
            exit_code = self.click_command.main(
                args=argv[2:], prog_name=prog_name, standalone_mode=False
            )
            if exit_code:
                sys.exit(exit_code)
        except click.ClickException as e:
            if getattr(e, "ctx", False) and getattr(e.ctx, "traceback", False):  # NOCOV
                raise
            e.show()
            sys.exit(e.exit_code)
