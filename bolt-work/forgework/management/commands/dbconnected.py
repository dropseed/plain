import sys

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    """Django command that checks for database to be available and fails if not"""

    def handle(self, *args, **options):
        try:
            connection.ensure_connection()
            self.stdout.write("Database available")
        except OperationalError:
            self.stderr.write("Database unavailable")
            sys.exit(1)
