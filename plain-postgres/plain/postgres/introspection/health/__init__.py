"""Database health checks.

Public surface:
- Types: CheckItem, CheckResult, Informational, TableOwner
- Entry point: run_all_checks(cursor, table_owners) -> (results, context)
- Table ownership: build_table_owners()

Internal layout (for maintainers):
- types.py             — TypedDicts + Literals
- ownership.py         — build_table_owners, _table_info
- context.py           — gather_context (hit ratios, XID age, connections,
                         pg_stat_statements availability, etc.)
- helpers.py           — formatting and pg_stat_statements probes
- checks_structural.py — invalid/duplicate/missing_fk indexes, sequence exhaustion
- checks_cumulative.py — stats_freshness, vacuum_health, index_bloat,
                         unused_indexes, missing_index_candidates
- checks_snapshot.py   — long_running_connections, blocking_queries
- runner.py            — ALL_CHECKS + cross-check caveats + run_all_checks
"""

from __future__ import annotations

from .ownership import build_table_owners
from .runner import run_all_checks
from .types import CheckItem, CheckResult, Informational, TableOwner

__all__ = [
    "CheckItem",
    "CheckResult",
    "Informational",
    "TableOwner",
    "build_table_owners",
    "run_all_checks",
]
