import importlib
import os
import subprocess
import sys

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


cli = click.CommandCollection(sources=[NamespaceGroup(), root_cli])


if __name__ == "__main__":
    cli()
