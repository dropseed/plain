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
    ConstraintModelDrift,
    ConstraintNameDrift,
    ConstraintRenameDrift,
    Drift,
    DriftKind,
    ForeignKeyChangedDrift,
    ForeignKeyMissingDrift,
    ForeignKeyNameDrift,
    IndexModelDrift,
    IndexRenameDrift,
    IndexUndeclaredDrift,
    StorageParameterDeclaredDrift,
    StorageParameterUndeclaredDrift,
    analyze_model,
)
from .corrections import (
    AddConstraintCorrection,
    AddForeignKeyCorrection,
    Correction,
    CreateIndexCorrection,
    DropColumnDefaultCorrection,
    DropConstraintCorrection,
    DropIndexCorrection,
    DropNotNullCorrection,
    RebuildIndexCorrection,
    RenameConstraintCorrection,
    RenameIndexCorrection,
    ReplaceForeignKeyCorrection,
    ResetStorageParameterCorrection,
    SetColumnDefaultCorrection,
    SetNotNullCorrection,
    SetStorageParameterCorrection,
    ValidateConstraintCorrection,
)

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


# Plan items — drift + policy + executable action


@dataclass
class PlanItem:
    """A planned convergence action: drift description + policy + optional correction."""

    drift: Drift
    correction: Correction | None = None
    blocks_sync: bool = True
    guidance: str | None = None

    def describe(self) -> str:
        if self.correction:
            return self.correction.describe()
        return self.drift.describe()


def _plan_drift(drift: Drift) -> PlanItem:
    """Map a semantic drift to a plan item with policy. All policy lives here."""
    match drift:
        case IndexModelDrift(kind=DriftKind.MISSING, table=t, index=idx, model=m):
            return PlanItem(drift, CreateIndexCorrection(t, idx, m), blocks_sync=False)
        case IndexModelDrift(table=t, index=idx, model=m):  # INVALID | CHANGED
            return PlanItem(drift, RebuildIndexCorrection(t, idx, m), blocks_sync=False)
        case IndexRenameDrift(table=t, old_name=old, new_name=new):
            return PlanItem(
                drift, RenameIndexCorrection(t, old, new), blocks_sync=False
            )
        case IndexUndeclaredDrift(table=t, name=n):
            return PlanItem(drift, DropIndexCorrection(t, n), blocks_sync=False)
        case ConstraintModelDrift(
            kind=DriftKind.MISSING, table=t, constraint=c, model=m
        ):
            return PlanItem(drift, AddConstraintCorrection(t, c, m))
        case ConstraintModelDrift(kind=DriftKind.CHANGED):
            return PlanItem(
                drift,
                correction=None,
                guidance=(
                    "Declare a new constraint under a new name, run sync to add it,"
                    " then remove the old one."
                ),
            )
        case ConstraintNameDrift(kind=DriftKind.UNVALIDATED, table=t, name=n):
            return PlanItem(drift, ValidateConstraintCorrection(t, n))
        case ConstraintNameDrift(kind=DriftKind.UNDECLARED, table=t, name=n):
            return PlanItem(drift, DropConstraintCorrection(t, n))
        case ConstraintRenameDrift(table=t, old_name=old, new_name=new):
            return PlanItem(
                drift, RenameConstraintCorrection(t, old, new), blocks_sync=False
            )
        case ForeignKeyMissingDrift(
            table=t,
            name=n,
            column=col,
            target_table=tt,
            target_column=tc,
            on_delete_clause=od,
        ):
            return PlanItem(drift, AddForeignKeyCorrection(t, n, col, tt, tc, od))
        case ForeignKeyChangedDrift(
            table=t,
            name=n,
            column=col,
            target_table=tt,
            target_column=tc,
            on_delete_clause=od,
        ):
            return PlanItem(drift, ReplaceForeignKeyCorrection(t, n, col, tt, tc, od))
        case ForeignKeyNameDrift(kind=DriftKind.UNVALIDATED, table=t, name=n):
            return PlanItem(drift, ValidateConstraintCorrection(t, n))
        case ForeignKeyNameDrift(kind=DriftKind.UNDECLARED, table=t, name=n):
            return PlanItem(drift, DropConstraintCorrection(t, n))
        case ColumnShouldBeNotNullDrift(has_null_rows=False, table=t, column=col):
            return PlanItem(drift, SetNotNullCorrection(t, col))
        case ColumnShouldBeNotNullDrift(has_null_rows=True):
            return PlanItem(
                drift,
                correction=None,
                guidance="Backfill existing NULL rows, then rerun sync.",
            )
        case ColumnShouldAllowNullDrift(table=t, column=col):
            return PlanItem(drift, DropNotNullCorrection(t, col))
        case ColumnDefaultExpectedDrift(table=t, column=col, model_default_sql=sql):
            return PlanItem(drift, SetColumnDefaultCorrection(t, col, sql))
        case ColumnDefaultUndeclaredDrift(table=t, column=col):
            return PlanItem(drift, DropColumnDefaultCorrection(t, col))
        case StorageParameterDeclaredDrift(table=t, key=k, declared_value=v):
            return PlanItem(drift, SetStorageParameterCorrection(t, k, v))
        case StorageParameterUndeclaredDrift(table=t, key=k):
            return PlanItem(drift, ResetStorageParameterCorrection(t, k))
        case _:
            raise ValueError(f"Unhandled drift: {drift}")


def can_auto_correct(drift: Drift) -> bool:
    """Whether convergence can resolve this drift automatically.

    Used by the schema command for display (correctable vs non-correctable).
    Delegates to _plan_drift so policy has a single source of truth.
    """
    return _plan_drift(drift).correction is not None


# Execution results


@dataclass
class CorrectionResult:
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
        return [item for item in self.items if item.correction is not None]

    def has_work(self) -> bool:
        """Would execution produce any items?"""
        return bool(self.executable())

    @property
    def blocked(self) -> list[PlanItem]:
        """Items that cannot be auto-resolved (require staged rollout)."""
        return [item for item in self.items if item.correction is None]


# Convergence result


@dataclass
class ConvergenceResult:
    """Outcome of executing convergence plan items."""

    results: list[CorrectionResult] = field(default_factory=list)

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
    def blocking_failures(self) -> list[CorrectionResult]:
        return [r for r in self.results if not r.ok and r.item.blocks_sync]

    @property
    def non_blocking_failures(self) -> list[CorrectionResult]:
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

    items.sort(
        key=lambda item: item.correction.pass_order if item.correction else float("inf")
    )
    return ConvergencePlan(items=items)


def plan_model_convergence(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> ConvergencePlan:
    """Produce a convergence plan for a single model."""
    items = [_plan_drift(d) for d in analyze_model(conn, cursor, model).drifts]
    items.sort(
        key=lambda item: item.correction.pass_order if item.correction else float("inf")
    )
    return ConvergencePlan(items=items)


def execute_plan(items: Sequence[PlanItem]) -> ConvergenceResult:
    """Apply plan items independently, collecting results.

    Each item is applied and committed independently so partial
    failures don't block subsequent items.
    """
    result = ConvergenceResult()
    for item in items:
        # Callers pass plan.executable(), which excludes guidance-only items.
        assert item.correction is not None, (
            "execute_plan requires items with a correction"
        )
        try:
            sql = item.correction.apply()
            result.results.append(CorrectionResult(item=item, sql=sql))
        except Exception as e:
            result.results.append(CorrectionResult(item=item, error=e))
    return result
