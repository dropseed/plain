from __future__ import annotations

from typing import Any, Protocol

from .checks_cumulative import (
    check_index_bloat,
    check_missing_index_candidates,
    check_stats_freshness,
    check_unused_indexes,
    check_vacuum_health,
)
from .checks_snapshot import check_blocking_queries, check_long_running_connections
from .checks_structural import (
    check_duplicate_indexes,
    check_invalid_indexes,
    check_missing_fk_indexes,
    check_sequence_exhaustion,
)
from .context import gather_context
from .types import CheckResult, CheckTier, TableOwner


class CheckFn(Protocol):
    """Shape of every check function in ALL_CHECKS.

    Plain ``Callable[...]`` would type-check the call signature but strips
    `__name__`, which `run_all_checks` uses to synthesize a CheckResult
    when a check raises unexpectedly. Declaring the Protocol preserves
    both — and the set-of-callables tier registry below can be typed
    against it without casts.
    """

    __name__: str

    def __call__(
        self, cursor: Any, table_owners: dict[str, TableOwner]
    ) -> CheckResult: ...


ALL_CHECKS: list[CheckFn] = [
    # Structural (always-real).
    check_invalid_indexes,
    check_duplicate_indexes,
    check_missing_fk_indexes,
    check_sequence_exhaustion,
    # Upstream-issue — fix first so operational checks are trustworthy.
    check_stats_freshness,
    # Operational (depends on cumulative stats).
    check_vacuum_health,
    check_index_bloat,
    check_unused_indexes,
    check_missing_index_candidates,
    # Point-in-time snapshot.
    check_long_running_connections,
    check_blocking_queries,
]

# Checks whose findings render as operational context, not alarms. Kept as a
# frozenset of callables (not a name→tier map) so renaming a check function
# forces a same-commit update here — no string drift, no type ignores.
# The success path reads tier from the CheckResult the check returns; this
# set only controls the fallback CheckResult synthesized on unexpected
# exceptions in run_all_checks. Warning-tier is the default.
_OPERATIONAL_CHECKS: frozenset[CheckFn] = frozenset(
    {
        check_stats_freshness,
        check_vacuum_health,
        check_index_bloat,
    }
)


def _tier_for(check_fn: CheckFn) -> CheckTier:
    return "operational" if check_fn in _OPERATIONAL_CHECKS else "warning"


def _apply_cross_check_caveats(results: list[CheckResult]) -> None:
    """Annotate findings with context from other checks.

    Some checks depend on data other checks produce — e.g. `unused_indexes`
    relies on idx_scan counters but the planner's choice of index can be
    skewed if ANALYZE hasn't run (stats_freshness) or if the table has heavy
    bloat (vacuum_health). Without this pass, a user can't tell that an
    "unused index" finding may be an artifact of another problem.

    Each caveat is a short, plain-language string attached to the item in a
    new `caveats` list. The CLI renders these dim, under the suggestion.
    """
    # Build tables → set of check names that flagged them.
    flagged_by: dict[str, set[str]] = {}
    for r in results:
        for item in r["items"]:
            if item["table"]:
                flagged_by.setdefault(item["table"], set()).add(r["name"])

    # affected_check -> list of (upstream_check, caveat_text)
    CAVEATS: dict[str, list[tuple[str, str]]] = {
        "unused_indexes": [
            (
                "stats_freshness",
                "planner statistics on this table are absent or stale — the "
                "planner may be picking sub-optimal plans that bypass this "
                "index; re-check after ANALYZE",
            ),
            (
                "vacuum_health",
                "heavy dead-tuple bloat on this table may be skewing scan "
                "counts — clear the bloat before deciding to drop",
            ),
        ],
        "missing_index_candidates": [
            (
                "stats_freshness",
                "this table's planner stats are absent or stale — the "
                "sequential-scan evidence is still valid, but query plans "
                "may shift after ANALYZE",
            ),
        ],
    }

    for r in results:
        rules = CAVEATS.get(r["name"])
        if not rules:
            continue
        for item in r["items"]:
            table = item["table"]
            if not table:
                continue
            flagged = flagged_by.get(table, set())
            for upstream, text in rules:
                if upstream in flagged:
                    item["caveats"].append(text)


def run_all_checks(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> tuple[list[CheckResult], dict[str, Any]]:
    results: list[CheckResult] = []
    for check_fn in ALL_CHECKS:
        try:
            result = check_fn(cursor, table_owners)
        except Exception as e:
            name = check_fn.__name__.removeprefix("check_")
            result = CheckResult(
                name=name,
                label=name.replace("_", " ").title(),
                status="error",
                summary="error",
                items=[],
                message=str(e),
                tier=_tier_for(check_fn),
            )
        results.append(result)

    _apply_cross_check_caveats(results)

    context = gather_context(cursor, table_owners)
    return results, context
