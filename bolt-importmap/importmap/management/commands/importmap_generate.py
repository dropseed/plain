from django.core.management.base import BaseCommand, CommandError

from ...core import Importmap


class Command(BaseCommand):
    help = "Generate importmap.lock"

    def handle(self, *args, **options):
        importmap = Importmap()
        importmap.load()
        # force option to make sure a new lock is updated? or trust the logic?
