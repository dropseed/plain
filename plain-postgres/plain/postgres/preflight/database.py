"""Preflight checks on the database connection and migration state."""

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
    """Reports migration records with no file on disk, and reports a database
    the planner would refuse.

    Orphan records are reported, never prescribed against: they are what
    rollback needs, and a branch switch or a package reset leaves them behind
    on purpose. Records a baseline retired are not orphans at all. A refusal
    (`postgres.migration_history`) is an error: `plain postgres sync` will
    stop at the same point, and this reports it before the release phase.
    """

    def run(self) -> list[PreflightResult]:
        # Import here to avoid circular import issues
        from plain.postgres.migrations.loader import MigrationLoader

        conn = get_connection()
        loader = MigrationLoader(conn, ignore_no_migrations=True)
        assert loader.disk_migrations is not None
        assert loader.applied_migrations is not None
        recorded = loader.applied_migrations

        results = [
            PreflightResult(fix=str(refusal), id="postgres.migration_history")
            for refusal in loader.baseline_status.refusals
        ]

        orphans = loader.orphan_records(recorded)
        if not orphans:
            return results

        existing_packages = set(loader.migrated_packages)
        from_existing = [m for m in orphans if m[0] in existing_packages]
        from_removed = [m for m in orphans if m[0] not in existing_packages]

        def listed(migrations: list[tuple[str, str]]) -> str:
            text = ", ".join(f"{pkg}.{name}" for pkg, name in migrations[:3])
            if len(migrations) > 3:
                text += f" (and {len(migrations) - 3} more)"
            return text

        count = len(orphans)
        message_parts = [
            f"Found {count} migration record{'s' if count != 1 else ''} with no file on disk."
        ]
        if from_existing:
            message_parts.append(f"From existing packages: {listed(from_existing)}.")
        if from_removed:
            message_parts.append(f"From removed packages: {listed(from_removed)}.")

        results.append(
            PreflightResult(
                fix=" ".join(message_parts),
                id="postgres.prunable_migrations",
                warning=True,
            )
        )
        return results
