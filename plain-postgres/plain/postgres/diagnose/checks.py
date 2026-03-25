from __future__ import annotations

from typing import Any

from .tables import _table_source
from .types import CheckItem, CheckResult, TableOwner


def _format_bytes(nbytes: int) -> str:
    value = float(nbytes)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(value) < 1024:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _index_suggestion(
    *,
    source: str,
    package: str,
    app_suggestion: str,
    unmanaged_suggestion: str,
) -> str:
    """Return the appropriate suggestion based on table ownership."""
    if source == "app":
        return app_suggestion
    elif source == "package":
        return f"Managed by {package} — not directly actionable in your app"
    return unmanaged_suggestion


def check_invalid_indexes(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Indexes from failed CREATE INDEX CONCURRENTLY — maintained on writes, never used for reads."""
    cursor.execute("""
        SELECT
            s.relname AS table_name,
            s.indexrelname AS index_name,
            pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
        FROM pg_catalog.pg_stat_user_indexes s
        JOIN pg_catalog.pg_index i ON s.indexrelid = i.indexrelid
        WHERE NOT i.indisvalid
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    for table_name, index_name, index_size in rows:
        source, package = _table_source(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=index_name,
                detail=index_size,
                source=source,
                package=package,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    app_suggestion=f'Drop and re-run the migration that created it: DROP INDEX CONCURRENTLY "{index_name}";',
                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{index_name}";',
                ),
            )
        )

    return CheckResult(
        name="invalid_indexes",
        label="Invalid indexes",
        status="warning" if items else "ok",
        summary=str(len(items)) if items else "none",
        items=items,
        message="",
    )


def check_duplicate_indexes(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Indexes where one is a column-prefix of another on the same table."""
    cursor.execute("""
        SELECT
            ct.relname AS table_name,
            ci.relname AS index_name,
            i.indkey::int[] AS column_numbers,
            i.indclass::int[] AS opclass_numbers,
            i.indisunique,
            pg_size_pretty(pg_relation_size(ci.oid)) AS index_size,
            pg_relation_size(ci.oid) AS index_size_bytes
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class ci ON ci.oid = i.indexrelid
        JOIN pg_catalog.pg_class ct ON ct.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = ct.relnamespace
        WHERE n.nspname = 'public'
          AND i.indisvalid
          AND i.indexprs IS NULL
          AND i.indpred IS NULL
        ORDER BY ct.relname, ci.relname
    """)
    rows = cursor.fetchall()

    # Group by table
    by_table: dict[str, list[tuple[str, list[int], list[int], bool, str, int]]] = {}
    for table_name, index_name, cols, opclasses, is_unique, size, size_bytes in rows:
        by_table.setdefault(table_name, []).append(
            (index_name, cols, opclasses, is_unique, size, size_bytes)
        )

    items: list[CheckItem] = []
    flagged: set[str] = set()  # avoid reporting the same index multiple times
    for table_name, indexes in by_table.items():
        for i, idx_a in enumerate(indexes):
            for idx_b in indexes[i + 1 :]:
                # Check both directions: is either a prefix of the other?
                for shorter, longer in [(idx_a, idx_b), (idx_b, idx_a)]:
                    name_s, cols_s, ops_s, unique_s, size_s, _ = shorter
                    name_l, cols_l, ops_l, _, _, _ = longer
                    if (
                        name_s not in flagged
                        and len(cols_s) < len(cols_l)
                        and cols_l[: len(cols_s)] == cols_s
                        and ops_l[: len(cols_s)] == ops_s
                        and not unique_s  # unique indexes serve a constraint purpose
                    ):
                        source, package = _table_source(table_name, table_owners)
                        app_suggestion = f'Remove "{name_s}" from model indexes/constraints, then run makemigrations'

                        items.append(
                            CheckItem(
                                table=table_name,
                                name=name_s,
                                detail=f"{size_s}, redundant with {name_l}",
                                source=source,
                                package=package,
                                suggestion=_index_suggestion(
                                    source=source,
                                    package=package,
                                    app_suggestion=app_suggestion,
                                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{name_s}";',
                                ),
                            )
                        )
                        flagged.add(name_s)

    return CheckResult(
        name="duplicate_indexes",
        label="Duplicate indexes",
        status="warning" if items else "ok",
        summary=str(len(items)) if items else "none",
        items=items,
        message="",
    )


def check_unused_indexes(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Indexes with zero scans since stats reset, excluding unique/expression/constraint-backing.

    Also excludes indexes that are the sole coverage for a FK column — even at
    0 scans, FK columns should always have index coverage for referential
    integrity enforcement (parent DELETE/UPDATE scans the child table).
    """
    cursor.execute("""
        SELECT
            s.relname AS table_name,
            s.indexrelname AS index_name,
            pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
            pg_relation_size(s.indexrelid) AS index_size_bytes
        FROM pg_catalog.pg_stat_user_indexes s
        JOIN pg_catalog.pg_index i ON s.indexrelid = i.indexrelid
        WHERE s.idx_scan = 0
          AND pg_relation_size(s.indexrelid) > 1048576
          AND 0 <> ALL (i.indkey)
          AND NOT i.indisunique
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_constraint c
              WHERE c.conindid = s.indexrelid
          )
          AND i.indisvalid
          AND NOT (
              -- Leading column is a FK column on this table
              EXISTS (
                  SELECT 1 FROM pg_catalog.pg_constraint fk
                  WHERE fk.conrelid = i.indrelid
                    AND fk.contype = 'f'
                    AND array_length(fk.conkey, 1) = 1
                    AND fk.conkey[1] = i.indkey[0]
              )
              -- And no other valid index covers that column as its leading column
              AND NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_index other
                  WHERE other.indrelid = i.indrelid
                    AND other.indexrelid != i.indexrelid
                    AND other.indisvalid
                    AND other.indkey[0] = i.indkey[0]
              )
          )
        ORDER BY pg_relation_size(s.indexrelid) DESC
    """)
    rows = cursor.fetchall()

    total_bytes = 0
    items: list[CheckItem] = []
    for table_name, index_name, index_size, index_size_bytes in rows:
        total_bytes += index_size_bytes
        source, package = _table_source(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=index_name,
                detail=f"{index_size}, 0 scans",
                source=source,
                package=package,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    app_suggestion=f'Remove "{index_name}" from model indexes/constraints, then run makemigrations',
                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{index_name}";',
                ),
            )
        )

    if items:
        summary = f"{len(items)} ({_format_bytes(total_bytes)})"
    else:
        summary = "none"

    return CheckResult(
        name="unused_indexes",
        label="Unused indexes",
        status="warning" if items else "ok",
        summary=summary,
        items=items,
        message="",
    )


def check_missing_fk_indexes(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Foreign key columns without a leading index — JOINs on these do sequential scans."""
    cursor.execute("""
        SELECT
            ct.relname AS table_name,
            a.attname AS column_name,
            cc.relname AS referenced_table,
            c.conname AS constraint_name
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class ct ON ct.oid = c.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = ct.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        JOIN pg_catalog.pg_class cc ON cc.oid = c.confrelid
        WHERE c.contype = 'f'
          AND array_length(c.conkey, 1) = 1
          AND n.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_index i
              WHERE i.indrelid = c.conrelid
                AND i.indkey[0] = c.conkey[1]
          )
        ORDER BY ct.relname, a.attname
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    for table_name, column_name, referenced_table, constraint_name in rows:
        source, package = _table_source(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=f"{table_name}.{column_name}",
                detail=f"references {referenced_table}",
                source=source,
                package=package,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    app_suggestion=f'Add an Index on ["{column_name}"] to the model, then run makemigrations',
                    unmanaged_suggestion=f'CREATE INDEX CONCURRENTLY ON "{table_name}" ("{column_name}");',
                ),
            )
        )

    return CheckResult(
        name="missing_fk_indexes",
        label="Missing FK indexes",
        status="warning" if items else "ok",
        summary=str(len(items)) if items else "none",
        items=items,
        message="",
    )


def check_sequence_exhaustion(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Identity sequences approaching their type max."""
    cursor.execute("""
        WITH sequences AS (
            SELECT
                s.seqrelid,
                s.seqtypid,
                s.seqmax,
                ps.last_value,
                ps.start_value
            FROM pg_catalog.pg_sequence s
            JOIN pg_catalog.pg_class c ON c.oid = s.seqrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_sequences ps ON ps.schemaname = n.nspname
                AND ps.sequencename = c.relname
        )
        SELECT
            d.refobjid::regclass AS table_name,
            a.attname AS column_name,
            seq.seqtypid::regtype AS data_type,
            COALESCE(seq.last_value, seq.start_value) AS current_value,
            seq.seqmax AS max_value,
            ROUND(
                100.0 * COALESCE(seq.last_value, seq.start_value) / seq.seqmax, 2
            ) AS pct_used
        FROM sequences seq
        JOIN pg_catalog.pg_depend d ON d.objid = seq.seqrelid
            AND d.deptype IN ('a', 'i')
            AND d.classid = 'pg_class'::regclass
            AND d.refclassid = 'pg_class'::regclass
        JOIN pg_catalog.pg_attribute a ON a.attrelid = d.refobjid
            AND a.attnum = d.refobjsubid
        WHERE ROUND(
            100.0 * COALESCE(seq.last_value, seq.start_value) / seq.seqmax, 2
        ) > 50
        ORDER BY pct_used DESC
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    worst_pct = 0.0
    for table_name, column_name, data_type, current_value, max_value, pct_used in rows:
        pct = float(pct_used)
        worst_pct = max(worst_pct, pct)
        table_str = str(table_name)
        source, package = _table_source(table_str, table_owners)
        items.append(
            CheckItem(
                table=table_str,
                name=f"{table_str}.{column_name}",
                detail=f"{data_type}, {pct_used}% used ({current_value:,} / {max_value:,})",
                source=source,
                package=package,
                suggestion=f'ALTER TABLE "{table_str}" ALTER COLUMN "{column_name}" SET DATA TYPE bigint;',
            )
        )

    if worst_pct >= 90:
        status = "critical"
    elif items:
        status = "warning"
    else:
        status = "ok"

    return CheckResult(
        name="sequence_exhaustion",
        label="Sequence exhaustion",
        status=status,
        summary=f"{worst_pct}% worst" if items else "all ok",
        items=items,
        message="",
    )


def check_xid_wraparound(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Transaction ID age approaching the 2B wraparound limit."""
    cursor.execute("""
        SELECT
            datname,
            age(datfrozenxid) AS xid_age,
            ROUND(100.0 * age(datfrozenxid) / 2147483648, 2) AS pct_towards_wraparound
        FROM pg_catalog.pg_database
        WHERE datallowconn
        ORDER BY age(datfrozenxid) DESC
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    worst_pct = 0.0
    for datname, xid_age, pct in rows:
        pct_float = float(pct)
        if pct_float > 25:
            worst_pct = max(worst_pct, pct_float)
            items.append(
                CheckItem(
                    table="",
                    name=datname,
                    detail=f"{pct}% towards wraparound ({xid_age:,} XIDs)",
                    source="",
                    package="",
                    suggestion="Investigate autovacuum health, consider VACUUM FREEZE",
                )
            )

    if worst_pct >= 40:
        status = "critical"
    elif items:
        status = "warning"
    else:
        status = "ok"

    # Show the current database's percentage even when ok
    current_pct = float(rows[0][2]) if rows else 0
    summary = f"{current_pct}%" if not items else f"{worst_pct}%"

    return CheckResult(
        name="xid_wraparound",
        label="XID wraparound",
        status=status,
        summary=summary,
        items=items,
        message="",
    )


def _check_hit_ratio(
    cursor: Any,
    *,
    name: str,
    label: str,
    catalog_table: str,
    hit_col: str,
    read_col: str,
) -> CheckResult:
    """Hit ratio check — below 98.5% indicates insufficient shared_buffers or RAM."""
    cursor.execute(f"""
        SELECT ROUND(
            100.0 * SUM({hit_col}) / NULLIF(SUM({hit_col}) + SUM({read_col}), 0), 2
        ) FROM {catalog_table}
    """)
    row = cursor.fetchone()
    ratio = float(row[0]) if row and row[0] is not None else 100.0

    return CheckResult(
        name=name,
        label=label,
        status="warning" if ratio < 98.5 else "ok",
        summary=f"{ratio}%",
        items=[],
        message="Consider increasing shared_buffers or adding more RAM"
        if ratio < 98.5
        else "",
    )


def check_cache_hit_ratio(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    return _check_hit_ratio(
        cursor,
        name="cache_hit_ratio",
        label="Cache hit ratio",
        catalog_table="pg_catalog.pg_statio_user_tables",
        hit_col="heap_blks_hit",
        read_col="heap_blks_read",
    )


def check_index_hit_ratio(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    return _check_hit_ratio(
        cursor,
        name="index_hit_ratio",
        label="Index hit ratio",
        catalog_table="pg_catalog.pg_statio_user_indexes",
        hit_col="idx_blks_hit",
        read_col="idx_blks_read",
    )


def check_vacuum_health(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Tables with significant dead tuple accumulation."""
    cursor.execute("""
        SELECT
            relname AS table_name,
            n_dead_tup,
            n_live_tup,
            CASE WHEN n_live_tup > 0
                THEN ROUND(100.0 * n_dead_tup / n_live_tup, 2)
                ELSE 0
            END AS dead_tuple_pct,
            last_autovacuum
        FROM pg_catalog.pg_stat_user_tables
        WHERE n_dead_tup > 1000
        ORDER BY n_dead_tup DESC
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    for table_name, n_dead, n_live, dead_pct, last_vacuum in rows:
        pct = float(dead_pct)
        if pct > 10:
            vacuum_info = str(last_vacuum)[:19] if last_vacuum else "never"
            source, package = _table_source(table_name, table_owners)
            items.append(
                CheckItem(
                    table=table_name,
                    name=table_name,
                    detail=f"{n_dead:,} dead tuples ({dead_pct}% of live), last vacuum: {vacuum_info}",
                    source=source,
                    package=package,
                    suggestion="Investigate autovacuum — it may be falling behind on this table",
                )
            )

    return CheckResult(
        name="vacuum_health",
        label="Vacuum health",
        status="warning" if items else "ok",
        summary=f"{len(items)} tables need attention" if items else "all ok",
        items=items,
        message="",
    )


ALL_CHECKS = [
    check_invalid_indexes,
    check_duplicate_indexes,
    check_unused_indexes,
    check_missing_fk_indexes,
    check_sequence_exhaustion,
    check_xid_wraparound,
    check_cache_hit_ratio,
    check_index_hit_ratio,
    check_vacuum_health,
]
