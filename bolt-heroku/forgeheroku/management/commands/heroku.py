from forgecore.commands import DjangoClickAliasCommand

from forgeheroku.cli import cli


class Command(DjangoClickAliasCommand):
    click_command = cli
