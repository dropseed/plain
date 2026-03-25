from __future__ import annotations

from typing import Any

import psycopg.errors

from .tables import _table_source
from .types import TableOwner


def gather_context(cursor: Any, table_owners: dict[str, TableOwner]) -> dict[str, Any]:
    """Collect contextual information that isn't pass/fail but helps interpretation."""
    context: dict[str, Any] = {}

    # Table sizes
    cursor.execute("""
        SELECT
            c.relname AS table_name,
            c.reltuples::bigint AS estimated_row_count,
            pg_total_relation_size(c.oid) AS total_size_bytes,
            pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
            pg_size_pretty(pg_relation_size(c.oid)) AS table_size,
            pg_size_pretty(pg_indexes_size(c.oid)) AS indexes_size,
            (SELECT count(*) FROM pg_catalog.pg_index i WHERE i.indrelid = c.oid) AS index_count
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname = 'public'
        ORDER BY total_size_bytes DESC
    """)
    context["tables"] = []
    for row in cursor.fetchall():
        source, package = _table_source(row[0], table_owners)
        context["tables"].append(
            {
                "table": row[0],
                "estimated_rows": max(row[1], 0),
                "total_size_bytes": row[2],
                "total_size": row[3],
                "table_size": row[4],
                "indexes_size": row[5],
                "index_count": row[6],
                "source": source,
                "package": package,
            }
        )

    # Connection usage
    cursor.execute("""
        SELECT
            (SELECT count(*) FROM pg_catalog.pg_stat_activity
             WHERE datname = current_database()) AS active_connections,
            (SELECT setting::int FROM pg_catalog.pg_settings
             WHERE name = 'max_connections') AS max_connections
    """)
    row = cursor.fetchone()
    context["connections"] = {
        "active": row[0],
        "max": row[1],
    }

    # Stats reset time
    cursor.execute("""
        SELECT stats_reset
        FROM pg_catalog.pg_stat_database
        WHERE datname = current_database()
    """)
    row = cursor.fetchone()
    if row and row[0]:
        context["stats_reset"] = row[0].isoformat()
    else:
        context["stats_reset"] = None

    # pg_stat_statements availability + slow queries
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_stat_statements'
        )
    """)
    has_pgss = cursor.fetchone()[0]

    if not has_pgss:
        context["pg_stat_statements"] = "not_installed"
        context["slow_queries"] = []
    else:
        try:
            cursor.execute("""
                SELECT
                    calls,
                    ROUND(total_exec_time::numeric, 2) AS total_time_ms,
                    ROUND(mean_exec_time::numeric, 2) AS mean_time_ms,
                    ROUND(
                        (100 * total_exec_time / NULLIF(SUM(total_exec_time) OVER (), 0))::numeric, 2
                    ) AS pct_total_time,
                    LEFT(query, 200) AS query
                FROM pg_stat_statements
                ORDER BY total_exec_time DESC
                LIMIT 10
            """)
            context["pg_stat_statements"] = "available"
            context["slow_queries"] = [
                {
                    "calls": row[0],
                    "total_time_ms": float(row[1]),
                    "mean_time_ms": float(row[2]),
                    "pct_total_time": float(row[3]),
                    "query": row[4],
                }
                for row in cursor.fetchall()
            ]
        except psycopg.errors.DatabaseError:
            context["pg_stat_statements"] = "no_permission"
            context["slow_queries"] = []

    return context
