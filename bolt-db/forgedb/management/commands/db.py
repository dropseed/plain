from forgecore.commands import DjangoClickAliasCommand

from forgedb.cli import cli


class Command(DjangoClickAliasCommand):
    click_command = cli
