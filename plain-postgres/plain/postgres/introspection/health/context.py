from __future__ import annotations

from typing import Any

import psycopg.errors

from .ownership import _table_info
from .types import Informational, TableOwner


def gather_context(cursor: Any, table_owners: dict[str, TableOwner]) -> dict[str, Any]:
    """Collect informational data about the database: hit ratios, XID age,
    connection utilization, table sizes, slow queries, etc. These are surfaced
    alongside check results but never produce warnings on their own — they give
    an agent or human the situational awareness to interpret check findings.
    """
    context: dict[str, Any] = {}
    informationals: list[Informational] = []
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
        source, package, model_class, model_file = _table_info(row[0], table_owners)
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

    # Cache hit ratio — below 98.5% can indicate insufficient shared_buffers
    # but is also volatile after restart (cold cache). Informational only.
    cursor.execute("""
        SELECT ROUND(
            100.0 * SUM(heap_blks_hit) / NULLIF(SUM(heap_blks_hit) + SUM(heap_blks_read), 0), 2
        ) FROM pg_catalog.pg_statio_user_tables
    """)
    row = cursor.fetchone()
    cache_hit_ratio = float(row[0]) if row and row[0] is not None else None
    if cache_hit_ratio is not None:
        informationals.append(
            Informational(
                name="cache_hit_ratio",
                label="Cache hit ratio",
                value=cache_hit_ratio,
                unit="%",
                note="volatile after restart; sustained <95% may indicate memory pressure",
            )
        )

    # Index hit ratio — same caveats.
    cursor.execute("""
        SELECT ROUND(
            100.0 * SUM(idx_blks_hit) / NULLIF(SUM(idx_blks_hit) + SUM(idx_blks_read), 0), 2
        ) FROM pg_catalog.pg_statio_user_indexes
    """)
    row = cursor.fetchone()
    index_hit_ratio = float(row[0]) if row and row[0] is not None else None
    if index_hit_ratio is not None:
        informationals.append(
            Informational(
                name="index_hit_ratio",
                label="Index hit ratio",
                value=index_hit_ratio,
                unit="%",
                note="",
            )
        )

    # XID wraparound age for current database. Managed Postgres usually
    # tunes autovacuum to keep this in check, but long-running transactions
    # or a disabled autovacuum can still let it climb.
    cursor.execute("""
        SELECT
            ROUND(100.0 * age(datfrozenxid) / 2147483648, 2) AS pct_towards_wraparound
        FROM pg_catalog.pg_database
        WHERE datname = current_database()
    """)
    row = cursor.fetchone()
    xid_pct = float(row[0]) if row and row[0] is not None else None
    if xid_pct is not None:
        informationals.append(
            Informational(
                name="xid_wraparound",
                label="XID wraparound",
                value=xid_pct,
                unit="% toward wraparound",
                note="catastrophic if it reaches 100%; autovacuum usually keeps this low, but long-running transactions can block the freeze process",
            )
        )

    # Connection utilization. Point-in-time snapshot.
    cursor.execute("""
        SELECT
            (SELECT count(*) FROM pg_catalog.pg_stat_activity
             WHERE datname = current_database()) AS active_connections,
            (SELECT setting::int FROM pg_catalog.pg_settings
             WHERE name = 'max_connections') AS max_connections
    """)
    row = cursor.fetchone()
    active_conns, max_conns = row[0], row[1]
    context["connections"] = {"active": active_conns, "max": max_conns}
    if max_conns:
        pct = round(100.0 * active_conns / max_conns, 1)
        informationals.append(
            Informational(
                name="connection_saturation",
                label="Connection saturation",
                value=pct,
                unit="%",
                note=f"{active_conns}/{max_conns} connections in use (snapshot)",
            )
        )

    # Stats reset time — tells you how much history the cumulative checks have.
    cursor.execute("""
        SELECT stats_reset
        FROM pg_catalog.pg_stat_database
        WHERE datname = current_database()
    """)
    row = cursor.fetchone()
    stats_reset_iso = row[0].isoformat() if row and row[0] else None
    context["stats_reset"] = stats_reset_iso
    informationals.append(
        Informational(
            name="stats_reset",
            label="Stats reset",
            value=stats_reset_iso,
            unit="",
            note="cumulative-stat checks (unused_indexes, missing_index_candidates) need sufficient history after this point to be reliable",
        )
    )

    # pg_stat_statements availability + slow queries.
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_stat_statements'
        )
    """)
    has_pgss = cursor.fetchone()[0]

    if not has_pgss:
        context["pg_stat_statements"] = "not_installed"
        context["slow_queries"] = []
        informationals.append(
            Informational(
                name="pg_stat_statements",
                label="pg_stat_statements",
                value="not_installed",
                unit="",
                note="install for query-level analysis",
            )
        )
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
            informationals.append(
                Informational(
                    name="pg_stat_statements",
                    label="pg_stat_statements",
                    value="available",
                    unit="",
                    note="",
                )
            )
        except psycopg.errors.DatabaseError:
            context["pg_stat_statements"] = "no_permission"
            context["slow_queries"] = []
            informationals.append(
                Informational(
                    name="pg_stat_statements",
                    label="pg_stat_statements",
                    value="no_permission",
                    unit="",
                    note="grant pg_read_all_stats to enable query analysis",
                )
            )

    context["informationals"] = informationals
    return context
