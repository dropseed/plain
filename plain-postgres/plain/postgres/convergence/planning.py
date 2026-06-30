from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..db import get_connection
from ..registry import models_registry
from .analysis import (
    ColumnDefaultExpectedDrift,
    ColumnDefaultUndeclaredDrift,
    ColumnShouldAllowNullDrift,
    ColumnShouldBeNotNullDrift,
    ConstraintDrift,
    Drift,
    DriftKind,
    ForeignKeyDrift,
    IndexDrift,
    StorageParameterDeclaredDrift,
    StorageParameterUndeclaredDrift,
    analyze_model,
)
from .fixes import (
    AddConstraintFix,
    AddForeignKeyFix,
    CreateIndexFix,
    DropColumnDefaultFix,
    DropConstraintFix,
    DropIndexFix,
    DropNotNullFix,
    Fix,
    RebuildIndexFix,
    RenameConstraintFix,
    RenameIndexFix,
    ReplaceForeignKeyFix,
    ResetStorageParameterFix,
    SetColumnDefaultFix,
    SetNotNullFix,
    SetStorageParameterFix,
    ValidateConstraintFix,
)

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


# Plan items — drift + policy + executable action


@dataclass
class PlanItem:
    """A planned convergence action: drift description + policy + optional fix."""

    drift: Drift
    fix: Fix | None = None
    blocks_sync: bool = True
    guidance: str | None = None

    def describe(self) -> str:
        if self.fix:
            return self.fix.describe()
        return self.drift.describe()


def _plan_drift(drift: Drift) -> PlanItem:
    """Map a semantic drift to a plan item with policy. All policy lives here."""
    match drift:
        case IndexDrift(kind=DriftKind.MISSING, table=t, index=idx, model=m) if (
            idx is not None and m is not None
        ):
            return PlanItem(drift, CreateIndexFix(t, idx, m), blocks_sync=False)
        case IndexDrift(
            kind=DriftKind.INVALID | DriftKind.CHANGED, table=t, index=idx, model=m
        ) if idx is not None and m is not None:
            return PlanItem(drift, RebuildIndexFix(t, idx, m), blocks_sync=False)
        case IndexDrift(
            kind=DriftKind.RENAMED, table=t, old_name=old, new_name=new
        ) if old is not None and new is not None:
            return PlanItem(drift, RenameIndexFix(t, old, new), blocks_sync=False)
        case IndexDrift(kind=DriftKind.UNDECLARED, table=t, name=n) if n is not None:
            return PlanItem(drift, DropIndexFix(t, n), blocks_sync=False)
        case ConstraintDrift(
            kind=DriftKind.MISSING, table=t, constraint=c, model=m
        ) if c is not None and m is not None:
            return PlanItem(drift, AddConstraintFix(t, c, m))
        case ConstraintDrift(kind=DriftKind.UNVALIDATED, table=t, name=n) if (
            n is not None
        ):
            return PlanItem(drift, ValidateConstraintFix(t, n))
        case ConstraintDrift(kind=DriftKind.CHANGED):
            return PlanItem(
                drift,
                fix=None,
                guidance=(
                    "Declare a new constraint under a new name, run sync to add it,"
                    " then remove the old one."
                ),
            )
        case ConstraintDrift(
            kind=DriftKind.RENAMED, table=t, old_name=old, new_name=new
        ) if old is not None and new is not None:
            return PlanItem(drift, RenameConstraintFix(t, old, new), blocks_sync=False)
        case ConstraintDrift(kind=DriftKind.UNDECLARED, table=t, name=n) if (
            n is not None
        ):
            return PlanItem(drift, DropConstraintFix(t, n))
        case ForeignKeyDrift(
            kind=DriftKind.MISSING,
            table=t,
            name=cn,
            column=col,
            target_table=tt,
            target_column=tc,
            on_delete_clause=od,
        ) if cn is not None and col is not None and tt is not None and tc is not None:
            return PlanItem(drift, AddForeignKeyFix(t, cn, col, tt, tc, od))
        case ForeignKeyDrift(
            kind=DriftKind.CHANGED,
            table=t,
            name=cn,
            column=col,
            target_table=tt,
            target_column=tc,
            on_delete_clause=od,
        ) if cn is not None and col is not None and tt is not None and tc is not None:
            return PlanItem(drift, ReplaceForeignKeyFix(t, cn, col, tt, tc, od))
        case ForeignKeyDrift(kind=DriftKind.UNVALIDATED, table=t, name=n) if (
            n is not None
        ):
            return PlanItem(drift, ValidateConstraintFix(t, n))
        case ForeignKeyDrift(kind=DriftKind.UNDECLARED, table=t, name=n) if (
            n is not None
        ):
            return PlanItem(drift, DropConstraintFix(t, n))
        case ColumnShouldBeNotNullDrift(has_null_rows=False):
            return PlanItem(drift, SetNotNullFix(drift.table, drift.column))
        case ColumnShouldBeNotNullDrift(has_null_rows=True):
            return PlanItem(
                drift,
                fix=None,
                guidance="Backfill existing NULL rows, then rerun sync.",
            )
        case ColumnShouldAllowNullDrift():
            return PlanItem(drift, DropNotNullFix(drift.table, drift.column))
        case ColumnDefaultExpectedDrift():
            return PlanItem(
                drift,
                SetColumnDefaultFix(
                    drift.table, drift.column, drift.model_default_sql
                ),
            )
        case ColumnDefaultUndeclaredDrift():
            return PlanItem(drift, DropColumnDefaultFix(drift.table, drift.column))
        case StorageParameterDeclaredDrift(table=t, key=k, declared_value=v):
            return PlanItem(drift, SetStorageParameterFix(t, k, v))
        case StorageParameterUndeclaredDrift(table=t, key=k):
            return PlanItem(drift, ResetStorageParameterFix(t, k))
        case _:
            raise ValueError(f"Unhandled drift: {drift}")


def can_auto_fix(drift: Drift) -> bool:
    """Whether convergence can resolve this drift automatically.

    Used by the schema command for display (fixable vs non-fixable).
    Delegates to _plan_drift so policy has a single source of truth.
    """
    return _plan_drift(drift).fix is not None


# Execution results


@dataclass
class FixResult:
    """Outcome of applying a single plan item."""

    item: PlanItem
    sql: str | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# Convergence plan


@dataclass
class ConvergencePlan:
    """All planned convergence actions, ready for filtering and execution."""

    items: list[PlanItem]

    def executable(self) -> list[PlanItem]:
        """Items eligible for execution, sorted by pass_order."""
        return [item for item in self.items if item.fix is not None]

    def has_work(self) -> bool:
        """Would execution produce any items?"""
        return bool(self.executable())

    @property
    def blocked(self) -> list[PlanItem]:
        """Items that cannot be auto-resolved (require staged rollout)."""
        return [item for item in self.items if item.fix is None]


# Convergence result


@dataclass
class ConvergenceResult:
    """Outcome of executing convergence plan items."""

    results: list[FixResult] = field(default_factory=list)

    @property
    def applied(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def ok_for_sync(self) -> bool:
        """True if no sync-blocking items failed."""
        return all(r.ok for r in self.results if r.item.blocks_sync)

    @property
    def blocking_failures(self) -> list[FixResult]:
        return [r for r in self.results if not r.ok and r.item.blocks_sync]

    @property
    def non_blocking_failures(self) -> list[FixResult]:
        return [r for r in self.results if not r.ok and not r.item.blocks_sync]

    @property
    def summary(self) -> str:
        parts = []
        if self.applied:
            parts.append(f"{self.applied} applied")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts) + "."


# Plan construction


def plan_convergence() -> ConvergencePlan:
    """Scan all models against the database and produce a convergence plan."""
    conn = get_connection()
    items: list[PlanItem] = []

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            for drift in analyze_model(conn, cursor, model).drifts:
                items.append(_plan_drift(drift))

    items.sort(key=lambda item: item.fix.pass_order if item.fix else float("inf"))
    return ConvergencePlan(items=items)


def plan_model_convergence(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> ConvergencePlan:
    """Produce a convergence plan for a single model."""
    items = [_plan_drift(d) for d in analyze_model(conn, cursor, model).drifts]
    items.sort(key=lambda item: item.fix.pass_order if item.fix else float("inf"))
    return ConvergencePlan(items=items)


def execute_plan(items: Sequence[PlanItem]) -> ConvergenceResult:
    """Apply plan items independently, collecting results.

    Each item is applied and committed independently so partial
    failures don't block subsequent items.
    """
    result = ConvergenceResult()
    for item in items:
        # Callers pass plan.executable(), which excludes guidance-only items.
        assert item.fix is not None, "execute_plan requires items with a fix"
        try:
            sql = item.fix.apply()
            result.results.append(FixResult(item=item, sql=sql))
        except Exception as e:
            result.results.append(FixResult(item=item, error=e))
    return result
