"""Preflight checks on the database connection and migration state."""

from __future__ import annotations

from plain.postgres.db import get_connection
from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings


@register_check("postgres.middleware_installed")
class CheckMiddlewareInstalled(PreflightCheck):
    """Errors if `DatabaseConnectionMiddleware` isn't in `MIDDLEWARE`.

    Without it, pooled connections are only released by GC at the end of
    each request — relying on refcount timing under load is a recipe for
    pool exhaustion under cyclic refs or delayed finalization.
    """

    REQUIRED = "plain.postgres.DatabaseConnectionMiddleware"

    def run(self) -> list[PreflightResult]:
        if self.REQUIRED in settings.MIDDLEWARE:
            return []
        return [
            PreflightResult(
                fix=(
                    f"Add '{self.REQUIRED}' to MIDDLEWARE so pooled "
                    "database connections are returned at the end of each "
                    "request. Place it first so its after_response runs "
                    "after any middleware that queries the database."
                ),
                id="postgres.middleware_not_installed",
            )
        ]


@register_check("postgres.postgres_version")
class CheckPostgresVersion(PreflightCheck):
    """Checks that the PostgreSQL server meets the minimum version requirement."""

    MINIMUM_VERSION = 16

    def run(self) -> list[PreflightResult]:
        conn = get_connection()
        conn.ensure_connection()
        assert conn.connection is not None
        major, minor = divmod(conn.connection.info.server_version, 10000)
        if major < self.MINIMUM_VERSION:
            return [
                PreflightResult(
                    fix=f"PostgreSQL {self.MINIMUM_VERSION} or later is required (found {major}.{minor}).",
                    id="postgres.postgres_version_too_old",
                )
            ]
        return []


@register_check("postgres.database_tables")
class CheckDatabaseTables(PreflightCheck):
    """Checks for unknown tables in the database when plain.postgres is available."""

    def run(self) -> list[PreflightResult]:
        from plain.postgres.introspection import get_unknown_tables

        unknown_tables = get_unknown_tables()

        if not unknown_tables:
            return []

        table_names = ", ".join(unknown_tables)
        return [
            PreflightResult(
                fix=f"Unknown tables in default database: {table_names}. "
                "Tables may be from packages/models that have been uninstalled. "
                "Make sure you have a backup, then run `plain postgres drop-unknown-tables` to remove them.",
                id="postgres.unknown_database_tables",
                warning=True,
            )
        ]


@register_check("postgres.prunable_migrations")
class CheckPrunableMigrations(PreflightCheck):
    """Warns about stale migration records in the database."""

    def run(self) -> list[PreflightResult]:
        # Import here to avoid circular import issues
        from plain.postgres.migrations.loader import MigrationLoader
        from plain.postgres.migrations.recorder import MigrationRecorder

        errors = []

        # Load migrations from disk and database
        conn = get_connection()
        loader = MigrationLoader(conn, ignore_no_migrations=True)
        recorder = MigrationRecorder(conn)
        recorded_migrations = recorder.applied_migrations()

        # disk_migrations should not be None after MigrationLoader initialization,
        # but check to satisfy type checker
        if loader.disk_migrations is None:
            return errors

        # Find all prunable migrations (recorded but not on disk)
        all_prunable = [
            migration
            for migration in recorded_migrations
            if migration not in loader.disk_migrations
        ]

        if not all_prunable:
            return errors

        # Separate into existing packages vs orphaned packages
        existing_packages = set(loader.migrated_packages)
        prunable_existing: list[tuple[str, str]] = []
        prunable_orphaned: list[tuple[str, str]] = []

        for migration in all_prunable:
            package, name = migration
            if package in existing_packages:
                prunable_existing.append(migration)
            else:
                prunable_orphaned.append(migration)

        # Build the warning message
        total_count = len(all_prunable)
        message_parts = [
            f"Found {total_count} stale migration record{'s' if total_count != 1 else ''} in the database."
        ]

        if prunable_existing:
            existing_list = ", ".join(
                f"{pkg}.{name}" for pkg, name in prunable_existing[:3]
            )
            if len(prunable_existing) > 3:
                existing_list += f" (and {len(prunable_existing) - 3} more)"
            message_parts.append(f"From existing packages: {existing_list}.")

        if prunable_orphaned:
            orphaned_list = ", ".join(
                f"{pkg}.{name}" for pkg, name in prunable_orphaned[:3]
            )
            if len(prunable_orphaned) > 3:
                orphaned_list += f" (and {len(prunable_orphaned) - 3} more)"
            message_parts.append(f"From removed packages: {orphaned_list}.")

        message_parts.append("Run 'plain migrations prune' to review and remove them.")

        errors.append(
            PreflightResult(
                fix=" ".join(message_parts),
                id="postgres.prunable_migrations",
                warning=True,
            )
        )

        return errors
