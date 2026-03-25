from __future__ import annotations

from typing import Any

from .checks import ALL_CHECKS
from .context import gather_context
from .tables import build_table_owners
from .types import CheckItem, CheckResult, TableOwner

__all__ = [
    "ALL_CHECKS",
    "CheckItem",
    "CheckResult",
    "TableOwner",
    "build_table_owners",
    "gather_context",
    "run_all_checks",
]


def run_all_checks(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> tuple[list[CheckResult], dict[str, Any]]:
    results: list[CheckResult] = []
    for check_fn in ALL_CHECKS:
        try:
            result = check_fn(cursor, table_owners)
        except Exception as e:
            result = CheckResult(
                name=check_fn.__name__.removeprefix("check_"),
                label=check_fn.__name__.removeprefix("check_")
                .replace("_", " ")
                .title(),
                status="error",
                summary="error",
                items=[],
                message=str(e),
            )
        results.append(result)

    context = gather_context(cursor, table_owners)
    return results, context
