from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..db import get_connection
from ..registry import models_registry
from .analysis import analyze_model
from .fixes import Fix, FixCategory

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


@dataclass
class FixResult:
    """Outcome of applying a single fix."""

    fix: Fix
    sql: str | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ConvergencePlan:
    """All detected convergence fixes, ready for filtering and execution."""

    fixes: list[Fix]

    def executable(self, *, drop_undeclared: bool = False) -> list[Fix]:
        """Fixes to apply in this mode, sorted by pass_order."""
        if drop_undeclared:
            return list(self.fixes)
        return [
            f
            for f in self.fixes
            if f.category not in {FixCategory.CLEANUP, FixCategory.CONTRACTION}
        ]

    def has_work(self, *, drop_undeclared: bool = False) -> bool:
        """Would this mode produce any fixes to apply?"""
        return bool(self.executable(drop_undeclared=drop_undeclared))

    @property
    def blocking_cleanup(self) -> list[Fix]:
        """Contraction fixes that block success — leaving them changes DB behavior."""
        return [f for f in self.fixes if f.category == FixCategory.CONTRACTION]

    @property
    def optional_cleanup(self) -> list[Fix]:
        """Cleanup fixes safe to defer — stale but non-behavioral."""
        return [f for f in self.fixes if f.category == FixCategory.CLEANUP]


@dataclass
class ConvergenceResult:
    """Outcome of executing convergence fixes."""

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
        """True if no sync-blocking fixes failed."""
        return all(r.ok for r in self.results if r.fix.blocks_sync)

    @property
    def blocking_failures(self) -> list[FixResult]:
        return [r for r in self.results if not r.ok and r.fix.blocks_sync]

    @property
    def non_blocking_failures(self) -> list[FixResult]:
        return [r for r in self.results if not r.ok and not r.fix.blocks_sync]

    @property
    def summary(self) -> str:
        parts = []
        if self.applied:
            parts.append(f"{self.applied} applied")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts) + "."


def plan_convergence() -> ConvergencePlan:
    """Scan all models against the database and produce a convergence plan."""
    conn = get_connection()
    fixes: list[Fix] = []

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            fixes.extend(analyze_model(conn, cursor, model).fixes)

    fixes.sort(key=lambda f: f.pass_order)
    return ConvergencePlan(fixes=fixes)


def plan_model_convergence(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> ConvergencePlan:
    """Produce a convergence plan for a single model."""
    fixes = list(analyze_model(conn, cursor, model).fixes)
    fixes.sort(key=lambda f: f.pass_order)
    return ConvergencePlan(fixes=fixes)


def execute_fixes(fixes: Sequence[Fix]) -> ConvergenceResult:
    """Apply fixes independently, collecting results.

    Each fix is applied and committed independently so partial
    failures don't block subsequent fixes.
    """
    result = ConvergenceResult()
    for fix in fixes:
        try:
            sql = fix.apply()
            result.results.append(FixResult(fix=fix, sql=sql))
        except Exception as e:
            result.results.append(FixResult(fix=fix, error=e))
    return result
