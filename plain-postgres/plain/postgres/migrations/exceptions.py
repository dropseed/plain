from __future__ import annotations

from typing import Any

import psycopg


class AmbiguityError(Exception):
    """More than one migration matches a name prefix."""


class BadMigrationError(Exception):
    """There's a bad migration (unreadable/bad format/etc.)."""


class CircularDependencyError(Exception):
    """There's an impossible-to-resolve circular dependency."""


class InconsistentMigrationHistory(Exception):
    """An applied migration has some of its dependencies not applied."""


class InvalidBasesError(ValueError):
    """A model's base classes can't be resolved."""


class NodeNotFoundError(LookupError):
    """An attempt on a node is made that is not available in the graph."""

    def __init__(self, message: str, node: Any, origin: Any = None) -> None:
        self.message = message
        self.origin = origin
        self.node = node

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"NodeNotFoundError({self.node!r})"


class MigrationSchemaMissing(psycopg.DatabaseError):
    pass


class MigrationSchemaError(Exception):
    """The model graph contains a schema change that cannot be safely
    translated to a single migration — e.g. adding a NOT NULL field to
    an existing table without a default, which would leave existing rows
    with no value."""


class MigrationHistoryError(Exception):
    """The planner refuses to touch this database until an operator acts.

    Raised by `MigrationExecutor.migration_plan`; preflight runs the same
    classification and reports these as errors instead. `str(err)` is the
    operator-facing message.
    """

    package_label: str


class ResetBoundaryError(MigrationHistoryError):
    """This database's records predate a package's migration reset."""

    def __init__(self, package_label: str, sentinel: str, since: str) -> None:
        self.package_label = package_label
        super().__init__(
            f"Migration records for `{package_label}` predate the reset shipped in "
            f"{f'version {since} of `{package_label}`' if since else 'a later release'}: "
            f"`{package_label}.{sentinel}` was never applied "
            f"to this database. Upgrade through the last release that still includes "
            f"`{package_label}.{sentinel}`, run `plain postgres sync`, then upgrade again."
        )


class StaleMigrationRecordsError(MigrationHistoryError):
    """A package has migration records but some or all of its tables are gone."""

    def __init__(
        self, package_label: str, missing: list[str], expected: list[str]
    ) -> None:
        self.package_label = package_label
        if len(missing) == len(expected):
            what = f"none of its tables do (looked for: {', '.join(expected)})"
            remedy = f"run `plain migrations prune {package_label}` to drop them, then apply; the baseline will run"
        else:
            what = f"some of its tables are missing ({', '.join(missing)})"
            remedy = f"restore them, or drop the rest and run `plain migrations prune {package_label}`, then apply"
        super().__init__(
            f"Migration records exist for `{package_label}` but {what}. The records are stale - {remedy}."
        )


class UnrecordedTablesError(MigrationHistoryError):
    """A package has no migration records, but its tables are already there."""

    def __init__(
        self, package_label: str, baseline_name: str, tables: list[str]
    ) -> None:
        self.package_label = package_label
        super().__init__(
            f"`{package_label}` has no migration records, but its tables exist "
            f"(found: {', '.join(tables)}), so running its baseline would fail. If the "
            f"schema is current, record the baseline instead: "
            f"`plain migrations apply {package_label} {baseline_name} --fake`. "
            "If it isn't, drop those tables, then apply."
        )
