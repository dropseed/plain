"""Point-in-time snapshot checks — look at pg_stat_activity / pg_locks
right now, not at accumulated counters. Fire on live incidents
(blocker sessions, long-running idle-in-transaction, stuck queries)."""

from __future__ import annotations

from typing import Any

import psycopg.errors

from .types import CheckItem, CheckResult, CheckStatus, TableOwner

_SEVERITY_RANK: dict[CheckStatus, int] = {
    "ok": 0,
    "skipped": 0,
    "error": 0,
    "warning": 1,
    "critical": 2,
}


def _escalate(current: CheckStatus, new: CheckStatus) -> CheckStatus:
    """Return whichever of `current` or `new` has the higher severity."""
    return new if _SEVERITY_RANK[new] > _SEVERITY_RANK[current] else current


def check_blocking_queries(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Queries currently blocking other queries via held locks.

    Point-in-time snapshot using pg_blocking_pids. A blocker is a
    transaction holding a lock that one or more other transactions are
    waiting on. Classic cause of "my app is hanging" in incidents —
    common patterns: long-running migration, idle-in-transaction client
    forgotten with a row lock, or an aggregate query holding a share lock.

    Fires warning at any blocker with victims aged 30s+; critical at 5min+.
    """
    warn_age_sec = 30
    critical_age_sec = 300

    # Probe inside psycopg's `transaction()` so a permission-denied error
    # rolls back cleanly (via fresh txn in autocommit mode, savepoint in
    # transaction mode) and doesn't cascade-fail later checks.
    #
    # Wait time is taken from pg_locks.waitstart (PG 14+) — the time the
    # blocked pid started waiting on its lock. Using query_start would
    # over-report (it measures total query runtime, not lock wait), which
    # makes severity triage unreliable for long-running statements that
    # only block near the end.
    try:
        with cursor.connection.transaction():
            cursor.execute(
                """
                SELECT
                    blocking.pid AS blocker_pid,
                    COALESCE(blocking.application_name, '') AS blocker_app,
                    COALESCE(blocking.usename, '') AS blocker_user,
                    blocking.state AS blocker_state,
                    EXTRACT(EPOCH FROM (now() - blocking.state_change))::bigint
                        AS blocker_state_age_sec,
                    LEFT(COALESCE(blocking.query, ''), 200) AS blocker_query,
                    blocked.pid AS blocked_pid,
                    COALESCE(blocked.application_name, '') AS blocked_app,
                    EXTRACT(
                        EPOCH FROM (now() - COALESCE(bl.wait_started, blocked.state_change))
                    )::bigint AS blocked_age_sec,
                    LEFT(COALESCE(blocked.query, ''), 200) AS blocked_query
                FROM pg_stat_activity AS blocked
                JOIN pg_stat_activity AS blocking
                    ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
                LEFT JOIN LATERAL (
                    SELECT MIN(waitstart) AS wait_started
                    FROM pg_catalog.pg_locks
                    WHERE pid = blocked.pid
                      AND NOT granted
                      AND waitstart IS NOT NULL
                ) bl ON TRUE
                WHERE blocked.datname = current_database()
                  AND blocking.datname = current_database()
                ORDER BY blocking.pid, blocked_age_sec DESC
                """
            )
            rows = cursor.fetchall()
    except psycopg.errors.InsufficientPrivilege:
        return CheckResult(
            name="blocking_queries",
            label="Blocking queries",
            status="skipped",
            summary="insufficient privilege to read pg_stat_activity",
            items=[],
            message="Grant pg_read_all_stats to this role for this check.",
            tier="warning",
        )
    except psycopg.errors.DatabaseError as e:
        # Defensive catch: if pg_stat_activity/pg_locks hit an unexpected
        # server-side condition (column rename on a newer major, catalog
        # lock conflict, etc.), skip gracefully instead of letting the
        # failure cascade to run_all_checks.
        return CheckResult(
            name="blocking_queries",
            label="Blocking queries",
            status="skipped",
            summary="query failed",
            items=[],
            message=f"Blocking-queries probe failed: {e}",
            tier="warning",
        )

    # Group by blocker pid.
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        (
            blocker_pid,
            blocker_app,
            blocker_user,
            blocker_state,
            blocker_age,
            blocker_query,
            blocked_pid,
            blocked_app,
            blocked_age,
            blocked_query,
        ) = row
        entry = grouped.setdefault(
            blocker_pid,
            {
                "app": blocker_app,
                "user": blocker_user,
                "state": blocker_state,
                "state_age": blocker_age or 0,
                "query": (blocker_query or "").strip(),
                "victims": [],
            },
        )
        entry["victims"].append(
            {
                "pid": blocked_pid,
                "app": blocked_app,
                "age": blocked_age or 0,
                "query": (blocked_query or "").strip(),
            }
        )

    items: list[CheckItem] = []
    worst_severity: CheckStatus = "ok"
    for blocker_pid, info in grouped.items():
        # Age of the longest-waiting victim — that's how urgent this is.
        oldest_victim_age = max((v["age"] for v in info["victims"]), default=0)

        if oldest_victim_age >= critical_age_sec:
            severity: CheckStatus = "critical"
        elif oldest_victim_age >= warn_age_sec:
            severity = "warning"
        else:
            continue

        worst_severity = _escalate(worst_severity, severity)

        victim_lines = []
        for v in info["victims"]:
            victim_lines.append(
                f"      pid {v['pid']}: waiting {v['age']}s — "
                f"{(v['query'] or '(no query)')[:160]}"
            )

        app_tag = f" [{info['app']}]" if info["app"] else ""
        items.append(
            CheckItem(
                table="",
                name=f"pid {blocker_pid}{app_tag}",
                detail=(
                    f"blocking {len(info['victims'])} "
                    f"{'query' if len(info['victims']) == 1 else 'queries'} "
                    f"(oldest waiting {oldest_victim_age}s); "
                    f"blocker state: {info['state']} for {info['state_age']}s; "
                    f"blocker query: {(info['query'] or '(no query)')[:160]}\n"
                    + "\n".join(victim_lines)
                ),
                source="",
                package="",
                model_class="",
                model_file="",
                suggestion=(
                    f"If the blocker is stuck, terminate it: "
                    f"SELECT pg_terminate_backend({blocker_pid});"
                ),
                caveats=[],
            )
        )

    if worst_severity == "critical":
        summary = f"{len(items)} blocker(s) with critical-age waiters"
    elif items:
        summary = f"{len(items)} blocker(s)"
    else:
        summary = "none"

    return CheckResult(
        name="blocking_queries",
        label="Blocking queries",
        status=worst_severity if items else "ok",
        summary=summary,
        items=items,
        message="",
        tier="warning",
    )


def check_long_running_connections(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Client connections stuck in a transaction or running a query for too long.

    Idle-in-transaction holds row locks and blocks autovacuum; prolonged
    active queries often indicate a bad plan, a migration gone wrong, or an
    unindexed cleanup job. Excludes this backend and non-client backends
    (autovacuum workers, walsenders, etc).
    """
    idle_warn_seconds = 60
    idle_critical_seconds = 600  # 10 minutes
    active_warn_seconds = 300  # 5 minutes
    active_critical_seconds = 1800  # 30 minutes

    # Probe inside psycopg's `transaction()` so a permission-denied error
    # rolls back cleanly (via fresh txn in autocommit mode, savepoint in
    # transaction mode) and doesn't cascade-fail later checks.
    try:
        with cursor.connection.transaction():
            cursor.execute("""
                SELECT
                    pid,
                    COALESCE(application_name, '') AS application_name,
                    COALESCE(usename, '') AS usename,
                    state,
                    EXTRACT(EPOCH FROM (now() - state_change))::bigint AS state_age_sec,
                    EXTRACT(EPOCH FROM (now() - query_start))::bigint AS query_age_sec,
                    EXTRACT(EPOCH FROM (now() - xact_start))::bigint AS xact_age_sec,
                    LEFT(COALESCE(query, ''), 200) AS query
                FROM pg_catalog.pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND backend_type = 'client backend'
                  AND state IS NOT NULL
            """)
            rows = cursor.fetchall()
    except psycopg.errors.InsufficientPrivilege:
        return CheckResult(
            name="long_running_connections",
            label="Long-running connections",
            status="skipped",
            summary="insufficient privilege to read pg_stat_activity",
            items=[],
            message="Grant pg_read_all_stats to this role for this check.",
            tier="warning",
        )

    items: list[CheckItem] = []
    worst_severity: CheckStatus = "ok"
    for pid, app_name, usename, state, state_age, query_age, xact_age, query in rows:
        state_age = state_age or 0
        query_age = query_age or 0
        xact_age = xact_age or 0

        kind: str | None = None
        age: int = 0
        severity: CheckStatus = "ok"

        if state in ("idle in transaction", "idle in transaction (aborted)"):
            # Age the transaction by xact_start, not state_change — what matters
            # is how long this transaction has been open (holding locks, blocking
            # autovacuum), not just how long it's been sitting idle. A session
            # that spent 20 minutes in an open txn and idled 5 seconds ago is
            # still a 20-minute problem.
            age = xact_age or state_age
            if age >= idle_critical_seconds:
                kind, severity = state, "critical"
            elif age >= idle_warn_seconds:
                kind, severity = state, "warning"
        elif state == "active":
            age = query_age
            if age >= active_critical_seconds:
                kind, severity = "active query", "critical"
            elif age >= active_warn_seconds:
                kind, severity = "active query", "warning"

        if kind is None:
            continue

        worst_severity = _escalate(worst_severity, severity)

        app = f" [{app_name}]" if app_name else ""
        query_excerpt = query.strip() if query else ""
        if query_excerpt:
            query_excerpt = f" query: {query_excerpt}"

        items.append(
            CheckItem(
                table="",
                name=f"pid {pid}{app}",
                detail=f"{kind} for {age}s (user: {usename}){query_excerpt}",
                source="",
                package="",
                model_class="",
                model_file="",
                suggestion=(
                    "Investigate the client — if stuck, "
                    f"run: SELECT pg_terminate_backend({pid});"
                ),
                caveats=[],
            )
        )

    if worst_severity == "critical":
        summary = f"{len(items)} stuck connections (critical)"
    elif items:
        summary = f"{len(items)} long-running connections"
    else:
        summary = "all ok"

    return CheckResult(
        name="long_running_connections",
        label="Long-running connections",
        status=worst_severity if items else "ok",
        summary=summary,
        items=items,
        message="",
        tier="warning",
    )
