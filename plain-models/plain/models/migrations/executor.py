from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from plain.models.connections import DatabaseConnection

from ..transaction import atomic
from .loader import MigrationLoader
from .migration import Migration
from .recorder import MigrationRecorder
from .state import ProjectState

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper


class MigrationExecutor:
    """
    End-to-end migration execution - load migrations and run them up or down
    to a specified set of targets.
    """

    def __init__(
        self,
        connection: BaseDatabaseWrapper | DatabaseConnection,
        progress_callback: Callable[..., Any] | None = None,
    ) -> None:
        self.connection = connection
        self.loader = MigrationLoader(self.connection)
        self.recorder = MigrationRecorder(self.connection)
        self.progress_callback = progress_callback

    def migration_plan(
        self, targets: list[tuple[str, str]], clean_start: bool = False
    ) -> list[Migration]:
        """
        Given a set of targets, return a list of Migration instances.
        """
        plan = []
        if clean_start:
            applied = {}
        else:
            applied = dict(self.loader.applied_migrations)
        for target in targets:
            for migration in self.loader.graph.forwards_plan(target):
                if migration not in applied:
                    plan.append(self.loader.graph.nodes[migration])
                    applied[migration] = self.loader.graph.nodes[migration]
        return plan

    def _create_project_state(
        self, with_applied_migrations: bool = False
    ) -> ProjectState:
        """
        Create a project state including all the applications without
        migrations and applied migrations if with_applied_migrations=True.
        """
        state = ProjectState(real_packages=self.loader.unmigrated_packages)
        if with_applied_migrations:
            # Create the forwards plan Plain would follow on an empty database
            full_plan = self.migration_plan(
                self.loader.graph.leaf_nodes(), clean_start=True
            )
            applied_migrations = {
                self.loader.graph.nodes[key]
                for key in self.loader.applied_migrations
                if key in self.loader.graph.nodes
            }
            for migration in full_plan:
                if migration in applied_migrations:
                    migration.mutate_state(state, preserve=False)
        return state

    def migrate(
        self,
        targets: list[tuple[str, str]],
        plan: list[Migration] | None = None,
        state: ProjectState | None = None,
        fake: bool = False,
        atomic_batch: bool = False,
    ) -> ProjectState:
        """
        Migrate the database up to the given targets.

        Plain first needs to create all project states before a migration is
        (un)applied and in a second step run all the database operations.

        atomic_batch: Whether to run all migrations in a single transaction.
        """
        # The plain_migrations table must be present to record applied
        # migrations, but don't create it if there are no migrations to apply.
        if plan == []:
            if not self.recorder.has_table():
                return self._create_project_state(with_applied_migrations=False)
        else:
            self.recorder.ensure_schema()

        if plan is None:
            plan = self.migration_plan(targets)
        # Create the forwards plan Plain would follow on an empty database
        full_plan = self.migration_plan(
            self.loader.graph.leaf_nodes(), clean_start=True
        )

        if not plan:
            if state is None:
                # The resulting state should include applied migrations.
                state = self._create_project_state(with_applied_migrations=True)
        else:
            if state is None:
                # The resulting state should still include applied migrations.
                state = self._create_project_state(with_applied_migrations=True)

            migrations_to_run = set(plan)

            # Choose context manager based on atomic_batch
            batch_context = atomic if (atomic_batch and len(plan) > 1) else nullcontext

            with batch_context():
                for migration in full_plan:
                    if not migrations_to_run:
                        # We remove every migration that we applied from these sets so
                        # that we can bail out once the last migration has been applied
                        # and don't always run until the very end of the migration
                        # process.
                        break
                    if migration in migrations_to_run:
                        if "models_registry" not in state.__dict__:
                            state.models_registry  # Render all -- performance critical
                        state = self.apply_migration(state, migration, fake=fake)
                        migrations_to_run.remove(migration)

        self.check_replacements()

        assert state is not None
        return state

    def apply_migration(
        self, state: ProjectState, migration: Migration, fake: bool = False
    ) -> ProjectState:
        """Run a migration forwards."""
        migration_recorded = False
        if self.progress_callback:
            self.progress_callback("apply_start", migration=migration, fake=fake)
        if not fake:
            # Alright, do it normally
            with self.connection.schema_editor(
                atomic=migration.atomic
            ) as schema_editor:
                state = migration.apply(
                    state, schema_editor, operation_callback=self.progress_callback
                )
                if not schema_editor.deferred_sql:
                    self.record_migration(migration)
                    migration_recorded = True
        if not migration_recorded:
            self.record_migration(migration)
        # Report progress
        if self.progress_callback:
            self.progress_callback("apply_success", migration=migration, fake=fake)
        return state

    def record_migration(self, migration: Migration) -> None:
        # For replacement migrations, record individual statuses
        if migration.replaces:
            for package_label, name in migration.replaces:
                self.recorder.record_applied(package_label, name)
        else:
            self.recorder.record_applied(migration.package_label, migration.name)

    def check_replacements(self) -> None:
        """
        Mark replacement migrations applied if their replaced set all are.

        Do this unconditionally on every migrate, rather than just when
        migrations are applied or unapplied, to correctly handle the case
        when a new squash migration is pushed to a deployment that already had
        all its replaced migrations applied. In this case no new migration will
        be applied, but the applied state of the squashed migration must be
        maintained.
        """
        applied = self.recorder.applied_migrations()
        for key, migration in self.loader.replacements.items():
            all_applied = all(m in applied for m in migration.replaces)
            if all_applied and key not in applied:
                self.recorder.record_applied(*key)
