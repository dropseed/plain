"""A migration that still declares `replaces` fails to load with the recovery recipe.

Plain removed Django's squash mechanism. The only thing left of it is this
error: the loader runs for every command, so a leftover `replaces` surfaces
immediately, and the message is the complete sequence to get the database's
history back to ordinary records.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from click.testing import CliRunner
from migration_helpers import temp_migrations
from plain.postgres import get_connection
from plain.postgres.cli.migrations import apply
from plain.postgres.migrations.exceptions import BadMigrationError
from plain.postgres.migrations.loader import MigrationLoader
from plain.postgres.migrations.recorder import MigrationRecorder
from plain.test import raises

SQUASHED = """\
from plain.postgres import migrations


class Migration(migrations.Migration):
    replaces = (("examples", "0001_initial"),)
    dependencies = ()
    operations = ()
"""

DEPENDENT = """\
from plain.postgres import migrations


class Migration(migrations.Migration):
    dependencies = (("examples", "0001_squashed"),)
    operations = ()
"""

ORDINARY = """\
from plain.postgres import migrations


class Migration(migrations.Migration):
    dependencies = ()
    operations = ()
"""


@contextmanager
def examples_migrations() -> Generator[Path]:
    with temp_migrations("examples") as root:
        yield root / "examples"


def test_replaces_on_disk_fails_to_load_with_the_recipe() -> None:
    with examples_migrations() as migrations_dir:
        path = migrations_dir / "0001_squashed.py"
        path.write_text(SQUASHED)

        with raises(BadMigrationError) as caught:
            MigrationLoader(None)

        message = str(caught.exception)
        assert "examples.0001_squashed declares `replaces`" in message
        assert str(path) in message
        assert 'to ("examples", "0001_squashed")' in message
        assert "plain migrations apply examples 0001_squashed --fake" in message
        assert "plain migrations prune" in message


def test_same_migration_without_replaces_loads() -> None:
    with examples_migrations() as migrations_dir:
        (migrations_dir / "0001_squashed.py").write_text(ORDINARY)

        loader = MigrationLoader(None)

        assert loader.disk_migrations is not None
        assert ("examples", "0001_squashed") in loader.disk_migrations


def test_apply_fake_records_a_migration_that_applied_migrations_depend_on() -> None:
    """Step 3 of the recipe. An applied migration pointing at an unrecorded one
    is exactly the state the fake repairs, so the history check must not
    refuse it first."""
    with examples_migrations() as migrations_dir:
        (migrations_dir / "0001_squashed.py").write_text(ORDINARY)
        (migrations_dir / "0002_dependent.py").write_text(DEPENDENT)
        recorder = MigrationRecorder(get_connection())
        recorder.record_applied("examples", "0002_dependent")

        result = CliRunner().invoke(
            apply, ["examples", "0001_squashed", "--fake", "--no-input"]
        )

        assert result.exit_code == 0, result.output
        assert ("examples", "0001_squashed") in recorder.applied_migrations()
