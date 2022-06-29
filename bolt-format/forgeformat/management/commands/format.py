from forgecore.commands import DjangoClickAliasCommand

from forgeformat.cli import cli


class Command(DjangoClickAliasCommand):
    click_command = cli
