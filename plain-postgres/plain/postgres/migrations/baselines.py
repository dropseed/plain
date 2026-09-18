"""Decide what to do with a baseline migration: run it, record it, or refuse.

A baseline stands in for a package's deleted history (`Migration.supersedes`).
The loader computes this once, next to the records it observed, and stores it
as `loader.baseline_status`; the planner, preflight, and plain-dev all read
that. Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from plain.postgres.options import default_db_table

from .exceptions import (
    MigrationHistoryError,
    ResetBoundaryError,
    StaleMigrationRecordsError,
    UnrecordedTablesError,
)

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection

    from .loader import MigrationLoader
    from .migration import Migration


@dataclass
class BaselineStatus:
    # Baselines to record without running, before anything else runs.
    adopt: list[Migration] = field(default_factory=list)
    # Why the planner must stop, per package. `str(error)` is the operator message.
    refusals: list[MigrationHistoryError] = field(default_factory=list)

    @property
    def adopt_keys(self) -> set[tuple[str, str]]:
        return {(b.package_label, b.name) for b in self.adopt}


def classify_baselines(
    loader: MigrationLoader,
    applied: dict[tuple[str, str], Any],
    connection: DatabaseConnection,
) -> BaselineStatus:
    """
    For each package that ships a baseline:

    - baseline recorded -> nothing to do
    - no records for the package, no tables -> the planner runs it
    - no records for the package, tables present -> refuse: fake it or drop them
    - the superseded migration recorded -> adopt (if the tables are there)
    - records but not the superseded migration -> refuse, too old
    - records but tables missing -> refuse, stale records
    """
    status = BaselineStatus()
    if not loader.baselines:
        return status

    recorded_packages = {label for label, _name in applied}
    existing_tables: set[str] | None = None

    def tables_present(tables: list[str]) -> list[str]:
        nonlocal existing_tables
        if existing_tables is None:
            existing_tables = set(connection.table_names())
        return [table for table in tables if table in existing_tables]

    for package_label, baseline in loader.baselines.items():
        key = (package_label, baseline.name)
        if key in applied:
            continue
        if package_label not in recorded_packages:
            present = tables_present(applied_tables(loader, applied, baseline))
            if present:
                status.refusals.append(
                    UnrecordedTablesError(package_label, baseline.name, present)
                )
            continue
        assert baseline.supersedes is not None
        if (package_label, baseline.supersedes) not in applied:
            status.refusals.append(
                ResetBoundaryError(
                    package_label, baseline.supersedes, baseline.shipped_in
                )
            )
            continue

        tables = applied_tables(loader, applied, baseline)
        missing = [t for t in tables if t not in tables_present(tables)]
        if missing:
            status.refusals.append(
                StaleMigrationRecordsError(package_label, missing, tables)
            )
            continue

        status.adopt.append(baseline)

    return status


def applied_tables(
    loader: MigrationLoader, applied: dict[tuple[str, str], Any], baseline: Migration
) -> list[str]:
    """The package's tables as this database should have them right now.

    Replays the baseline plus whatever recorded migrations follow it, so a
    kept migration that renamed a table counts by its new name, and a pending
    one that hasn't run yet doesn't count at all.
    """
    package_label = baseline.package_label
    nodes = [(package_label, baseline.name)] + [
        key for key in applied if key[0] == package_label and key in loader.graph.nodes
    ]
    state = loader.graph.make_state(
        nodes=nodes, real_packages=loader.unmigrated_packages
    )
    return [
        model_state.options.get("db_table")
        or default_db_table(package_label, model_state.name)
        for (label, _name), model_state in state.models.items()
        if label == package_label
    ]
