from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from ..transaction import atomic
from .loader import MigrationLoader
from .migration import Migration
from .recorder import MigrationRecorder
from .state import ProjectState

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


class MigrationExecutor:
    """
    End-to-end migration execution - load migrations and run them up or down
    to a specified set of targets.
    """

    def __init__(
        self,
        connection: DatabaseConnection,
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
            applied_source = self.loader.applied_migrations or {}
            applied = dict(applied_source)
        for target in targets:
            for migration in self.loader.graph.forwards_plan(target):
                if migration not in applied:
                    plan.append(self.loader.graph.nodes[migration])
                    applied[migration] = self.loader.graph.nodes[migration]
        return plan  # ty: ignore[invalid-return-type] (graph.nodes may hold dummy None, never reached here)

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
            applied_source = self.loader.applied_migrations or {}
            applied_migrations = {
                self.loader.graph.nodes[key]
                for key in applied_source
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
                            state.models_registry  # noqa: B018 — cached-property render; performance critical
                        state = self.apply_migration(state, migration, fake=fake)
                        migrations_to_run.remove(migration)

        assert state is not None
        return state

    def apply_migration(
        self, state: ProjectState, migration: Migration, fake: bool = False
    ) -> ProjectState:
        """Run a migration forwards."""
        if self.progress_callback:
            self.progress_callback("apply_start", migration=migration, fake=fake)
        if fake:
            self.recorder.record_applied(migration.package_label, migration.name)
        else:
            with self.connection.schema_editor(
                atomic=migration.atomic
            ) as schema_editor:
                state = migration.apply(
                    state, schema_editor, operation_callback=self.progress_callback
                )
                # Recorded inside the schema editor's transaction, so the row
                # commits with the DDL or rolls back with it.
                self.recorder.record_applied(migration.package_label, migration.name)
        if self.progress_callback:
            self.progress_callback("apply_success", migration=migration, fake=fake)
        return state
