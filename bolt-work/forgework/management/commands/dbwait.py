import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    """Django command that waits for database to be available"""

    def handle(self, *args, **options):
        """Handle the command"""
        self.stdout.write("Waiting for database...")
        attempts = 1

        while True:
            try:
                connection.ensure_connection()
                break
            except OperationalError:
                self.stdout.write(
                    f"Database unavailable, waiting 1 second... (attempt {attempts})"
                )
                time.sleep(1)
                attempts += 1

        self.stdout.write("Database available!")
