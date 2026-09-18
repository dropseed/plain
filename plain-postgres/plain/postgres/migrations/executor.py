from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..transaction import atomic
from .loader import MigrationLoader
from .migration import Migration
from .recorder import MigrationRecorder
from .state import ProjectState

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


@dataclass(frozen=True, kw_only=True)
class PendingMigrations:
    """What a plan does to the database: migrations it runs, baselines it
    records without running."""

    run: int
    record: int

    @property
    def total(self) -> int:
        return self.run + self.record


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
        # A baseline an explicitly named --fake is recording by hand; the one
        # case the loader's refusal for that package is stepped around.
        self.repair_baseline: tuple[str, str] | None = None

    @property
    def record_only(self) -> set[tuple[str, str]]:
        """Baselines to record without running: the loader's adoptions, plus
        the one a named --fake is repairing."""
        keys = self.loader.baseline_status.adopt_keys
        if self.repair_baseline is not None:
            keys = keys | {self.repair_baseline}
        return keys

    def split_plan(self, plan: list[Migration]) -> PendingMigrations:
        record_only = self.record_only
        record = sum(
            (migration.package_label, migration.name) in record_only
            for migration in plan
        )
        return PendingMigrations(run=len(plan) - record, record=record)

    def migration_plan(
        self,
        targets: list[tuple[str, str]],
        clean_start: bool = False,
        repair_baseline: tuple[str, str] | None = None,
    ) -> list[Migration]:
        """
        Given a set of targets, return a list of Migration instances.

        A baseline the loader says to adopt stays in the plan and is recorded
        rather than run (see `record_only`). A package the loader refuses
        raises here when it is in the plan - except the one `repair_baseline`
        names, which an explicit `--fake` is recording by hand.
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
        if not clean_start:
            self.repair_baseline = repair_baseline
            packages = {m.package_label for m in plan if m is not None}
            for refusal in self.loader.baseline_status.refusals:
                if refusal.package_label not in packages:
                    continue
                if (
                    repair_baseline is not None
                    and refusal.package_label == repair_baseline[0]
                ):
                    continue
                raise refusal
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
            # An unrecorded baseline that a recorded migration depends on must
            # already be in the state: that dependent's models reference it.
            # Every other baseline - adopted or run - contributes its state at
            # its own turn, after its own dependencies have.
            applied_source = (
                set(self.loader.applied_migrations or {})
                | self._baselines_recorded_migrations_need()
            )
            applied_migrations = {
                self.loader.graph.nodes[key]
                for key in applied_source
                if key in self.loader.graph.nodes
            }
            for migration in full_plan:
                if migration in applied_migrations:
                    migration.mutate_state(state, preserve=False)
        return state

    def _baselines_recorded_migrations_need(self) -> set[tuple[str, str]]:
        """Unrecorded baselines that some recorded migration depends on.

        Their models are already referenced by state the pre-run replay
        builds, so they go in first. A baseline nothing recorded depends on
        waits its turn in plan order - preloading it would reference models
        of its own dependencies that may not be applied yet.
        """
        applied = self.loader.applied_migrations or {}
        candidates = {
            (label, baseline.name)
            for label, baseline in self.loader.baselines.items()
            if (label, baseline.name) not in applied
        }
        if not candidates:
            return set()
        needed_by_recorded: set[tuple[str, str]] = set()
        for key in applied:
            if key in self.loader.graph.nodes:
                needed_by_recorded.update(self.loader.graph.forwards_plan(key))
        return candidates & needed_by_recorded

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

        if state is None:
            # The resulting state should include applied migrations.
            state = self._create_project_state(with_applied_migrations=True)
        if plan:
            # Create the forwards plan Plain would follow on an empty database
            full_plan = self.migration_plan(
                self.loader.graph.leaf_nodes(), clean_start=True
            )

            migrations_to_run = set(plan)
            record_only = self.record_only

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
                        state = self.apply_migration(
                            state,
                            migration,
                            fake=fake,
                            record_only=(migration.package_label, migration.name)
                            in record_only,
                        )
                        migrations_to_run.remove(migration)

        return state

    def apply_migration(
        self,
        state: ProjectState,
        migration: Migration,
        fake: bool = False,
        record_only: bool = False,
    ) -> ProjectState:
        """Run a migration forwards.

        `record_only` is a baseline being adopted: the database already has
        its tables, so it is recorded without running - like `fake`, and
        reported to the callback as such.
        """
        if self.progress_callback:
            self.progress_callback(
                "apply_start", migration=migration, fake=fake or record_only
            )
        if fake or record_only:
            # Recorded, not run - but the project state still moves forward so
            # a migration that follows can build on what this one declares.
            # (A baseline the pre-run replay already put there is re-added
            # unchanged.)
            state = migration.mutate_state(state, preserve=False)
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
            self.progress_callback(
                "apply_success", migration=migration, fake=fake or record_only
            )
        return state
