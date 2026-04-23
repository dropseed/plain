from __future__ import annotations

import os
import re
from typing import Any

import psycopg.errors

from .types import PgssAvailability


def _format_bytes(nbytes: int) -> str:
    value = float(nbytes)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(value) < 1024:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _display_path(path: str) -> str:
    """Format an absolute source path relative to the Plain project root
    when possible, so CLI output matches the project-root-relative paths
    users actually see in their editor — and stays stable no matter where
    the CLI is invoked from. Falls back to cwd-relative, then to absolute
    when neither form is useful (different drive, or path is outside the
    project)."""
    if not path:
        return path

    # Prefer Plain's project root (APP_PATH.parent) so output doesn't drift
    # based on the invoking shell's cwd. Imported lazily to avoid a cycle
    # and to tolerate contexts where runtime isn't set up.
    bases: list[str] = []
    try:
        from plain.runtime import APP_PATH

        bases.append(str(APP_PATH.parent))
    except Exception:
        pass
    bases.append(os.getcwd())

    for base in bases:
        try:
            rel = os.path.relpath(path, base)
        except ValueError:
            continue
        if not rel.startswith(".."):
            return rel

    return path


def _index_suggestion(
    *,
    source: str,
    package: str,
    model_class: str = "",
    model_file: str = "",
    app_suggestion: str,
    unmanaged_suggestion: str,
) -> str:
    """Return the appropriate suggestion based on table ownership.

    When model_class and model_file are known, prefixes the app_suggestion
    with a concrete file:class pointer so agents and humans can jump
    directly to the code.
    """
    if source == "app":
        if model_class and model_file:
            return f"{_display_path(model_file)} :: {model_class} — {app_suggestion}"
        if model_class:
            return f"On model {model_class}: {app_suggestion}"
        return app_suggestion
    elif source == "package":
        return f"Managed by {package} — not directly actionable in your app"
    return unmanaged_suggestion


def _pgss_usable(cursor: Any) -> PgssAvailability:
    """Check pg_stat_statements availability for this role.

    Returns three states so callers can surface the right remediation —
    "install the extension" vs "grant pg_read_all_stats" are completely
    different fixes, and conflating them sends users down the wrong path.

    Probes inside psycopg's `transaction()` so a permission-denied error
    (common on managed Postgres where the extension is installed but
    only readable by admin roles) rolls back cleanly — whether the outer
    connection is in autocommit mode or inside a transaction — without
    cascade-failing every later check.
    """
    cursor.execute(
        "SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_stat_statements'"
    )
    if not cursor.fetchone():
        return "not_installed"
    try:
        with cursor.connection.transaction():
            cursor.execute("SELECT 1 FROM pg_stat_statements LIMIT 1")
    except psycopg.errors.DatabaseError:
        return "no_permission"
    return "usable"


def _top_queries_for_table(
    cursor: Any, table_name: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Pull top queries against a table from pg_stat_statements.

    Caller must confirm pg_stat_statements is usable (via ``_pgss_usable``)
    before calling.

    Matches on the table name appearing as a whole identifier, not a
    substring: uses a POSIX regex with word boundaries so `user_profile`
    doesn't accidentally match queries referencing `user` (SQL LIKE treats
    `_` as a single-char wildcard, which made the previous ILIKE approach
    both miss unquoted references and over-match underscored names).
    """
    # Escape regex metacharacters in the user-provided name, then build a
    # pattern that requires a non-identifier character (or string edge) on
    # either side. Identifier chars per Postgres are [A-Za-z0-9_].
    escaped = re.escape(table_name)
    pattern = rf"(^|[^A-Za-z0-9_]){escaped}($|[^A-Za-z0-9_])"
    # toplevel=true filters out queries executed inside functions/procs
    # (PG 14+ column, guaranteed on Plain's PG 16+ minimum). Without it,
    # a hot stored proc's inner SELECT can dominate the "top queries"
    # list and obscure the real app-level culprits.
    cursor.execute(
        """
        SELECT
            calls,
            ROUND(total_exec_time::numeric, 2) AS total_ms,
            rows,
            shared_blks_hit + shared_blks_read AS blks_total,
            LEFT(query, 300) AS query
        FROM pg_stat_statements
        WHERE query ~ %(pat)s
          AND toplevel
          AND query !~* '^\\s*EXPLAIN\\M'
        ORDER BY total_exec_time DESC
        LIMIT %(limit)s
        """,
        {"pat": pattern, "limit": limit},
    )

    out: list[dict[str, Any]] = []
    for calls, total_ms, rows_returned, blks_total, query in cursor.fetchall():
        calls = calls or 0
        blks_total = blks_total or 0
        rows_returned = rows_returned or 0
        out.append(
            {
                "calls": calls,
                "total_ms": float(total_ms or 0),
                "rows_returned": rows_returned,
                "blks_per_call": round(blks_total / calls, 1) if calls else 0,
                "rows_per_call": round(rows_returned / calls, 2) if calls else 0,
                "query": " ".join(query.split()) if query else "",
            }
        )
    return out
