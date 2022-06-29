from forgecore.commands import DjangoClickAliasCommand

from forgework.cli import cli


class Command(DjangoClickAliasCommand):
    click_command = cli
