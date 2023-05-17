import importlib
import os
import subprocess
import sys
import traceback
import select
from django.utils.datastructures import OrderedSet

import click

# from .core import Forge


class NamespaceGroup(click.Group):
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
        imported = self.import_module_cli("bolt" + name.replace("-", ""))
        if imported:
            return imported

        bin_path = os.path.join(os.path.dirname(sys.executable), self.COMMAND_PREFIX + name)
        if not os.path.exists(bin_path):
            return

        # Support multiple CLIs that came from the same package
        # by looking at the contents of the bin command itself
        with open(bin_path) as f:
            for line in f:
                if line.startswith("from bolt"):
                    module = line.split(" import ")[0].split()[-1]
                    imported = self.import_module_cli(module)
                    if imported:
                        return imported

    def import_module_cli(self, name):
        try:
            i = importlib.import_module(name)
            return i.cli
        except ImportError:
            # Built-in commands will appear here,
            # but so would failed imports of new ones
            pass
        except AttributeError as e:
            click.secho(f'Error importing "{name}":\n  {e}\n', fg="red")


@click.group()
def root_cli():
    pass


@root_cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("django_args", nargs=-1, type=click.UNPROCESSED)
def django(django_args):
    subprocess.check_call(
        [
            "python",
            "-m",
            "django",
            *django_args,
        ],
        env={
            **os.environ,
            "PYTHONPATH": os.path.join(os.getcwd(), "app"),
            "DJANGO_SETTINGS_MODULE": "settings",
        },
    )


# @root_cli.command
# def docs():
#     """Open the Forge documentation in your browser"""
#     subprocess.run(["open", "https://www.forgepackages.com/docs/?ref=cli"])


# @cli.command(
#     context_settings=dict(
#         ignore_unknown_options=True,
#     )
# )
# @click.argument("makemigrations_args", nargs=-1, type=click.UNPROCESSED)
# def makemigrations(makemigrations_args):
#     """Alias to Django `makemigrations`"""
#     result = Forge().manage_cmd("makemigrations", *makemigrations_args)
#     if result.returncode:
#         sys.exit(result.returncode)


# @cli.command(
#     context_settings=dict(
#         ignore_unknown_options=True,
#     )
# )
# @click.argument("migrate_args", nargs=-1, type=click.UNPROCESSED)
# def migrate(migrate_args):
#     """Alias to Django `migrate`"""
#     result = Forge().manage_cmd("migrate", *migrate_args)
#     if result.returncode:
#         sys.exit(result.returncode)


# @cli.command()
# def shell():
#     """Alias to Django `shell`"""
#     Forge().manage_cmd("shell")




@root_cli.command()
@click.option(
    "--no-startup",
    is_flag=True,
    help=(
        "When using plain Python, ignore the PYTHONSTARTUP environment "
        "variable and ~/.pythonrc.py script."
    ),
)
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
@click.option(
    "-c",
    "--command",
    help=(
        "Instead of opening an interactive shell, run a command as Django and "
        "exit."
    ),
)
def shell(no_startup, interface, command):
    """
    Runs a Python interactive interpreter. Tries to use IPython or
    bpython, if one of them is available. Any standard input is executed
    as code.
    """

    # Execute the command and exit.
    if command:
        exec(command, globals())
        return

    # Execute stdin if it has anything to read and exit.
    # Not supported on Windows due to select.select() limitations.
    if (
        sys.platform != "win32"
        and not sys.stdin.isatty()
        and select.select([sys.stdin], [], [], 0)[0]
    ):
        exec(sys.stdin.read(), globals())
        return


    def ipython_shell(no_startup):
        from IPython import start_ipython

        start_ipython(argv=[])

    def bpython_shell(no_startup):
        import bpython

        bpython.embed()

    def python_shell(no_startup):
        import code

        # Set up a dictionary to serve as the environment for the shell.
        imported_objects = {}

        # We want to honor both $PYTHONSTARTUP and .pythonrc.py, so follow system
        # conventions and get $PYTHONSTARTUP first then .pythonrc.py.
        if not no_startup:
            for pythonrc in OrderedSet(
                [os.environ.get("PYTHONSTARTUP"), os.path.expanduser("~/.pythonrc.py")]
            ):
                if not pythonrc:
                    continue
                if not os.path.isfile(pythonrc):
                    continue
                with open(pythonrc) as handle:
                    pythonrc_code = handle.read()
                # Match the behavior of the cpython shell where an error in
                # PYTHONSTARTUP prints an exception and continues.
                try:
                    exec(compile(pythonrc_code, pythonrc, "exec"), imported_objects)
                except Exception:
                    traceback.print_exc()

        # By default, this will set up readline to do tab completion and to read and
        # write history to the .python_history file, but this can be overridden by
        # $PYTHONSTARTUP or ~/.pythonrc.py.
        try:
            hook = sys.__interactivehook__
        except AttributeError:
            # Match the behavior of the cpython shell where a missing
            # sys.__interactivehook__ is ignored.
            pass
        else:
            try:
                hook()
            except Exception:
                # Match the behavior of the cpython shell where an error in
                # sys.__interactivehook__ prints a warning and the exception
                # and continues.
                print("Failed calling sys.__interactivehook__")
                traceback.print_exc()

        # Set up tab completion for objects imported by $PYTHONSTARTUP or
        # ~/.pythonrc.py.
        try:
            import readline
            import rlcompleter

            readline.set_completer(rlcompleter.Completer(imported_objects).complete)
        except ImportError:
            pass

        # Start the interactive interpreter.
        code.interact(local=imported_objects)

    available_shells = [interface] if interface else ["ipython", "bpython", "python"]

    for shell in available_shells:
        try:
            if shell == "ipython":
                return ipython_shell(no_startup)
            elif shell == "bpython":
                return bpython_shell(no_startup)
            elif shell == "python":
                return python_shell(no_startup)
        except ImportError:
            pass
    
    click.secho(f"Couldn't import {shell} interface.", fg="red")
    sys.exit(1)


cli = click.CommandCollection(sources=[NamespaceGroup(), root_cli])


if __name__ == "__main__":
    cli()
