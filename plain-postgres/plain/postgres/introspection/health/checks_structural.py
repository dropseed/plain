"""Structural checks — always-real findings against the current schema.

These fire the moment the condition exists; they don't depend on
accumulated stats since the last reset. Each has an immediately
actionable remediation in the user's code (or SQL for unmanaged tables)."""

from __future__ import annotations

from typing import Any

from .helpers import _index_suggestion
from .ownership import _table_info
from .types import CheckItem, CheckResult, TableOwner


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
        source, package, model_class, model_file = _table_info(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=index_name,
                detail=index_size,
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    model_class=model_class,
                    model_file=model_file,
                    app_suggestion=f'Drop and re-run the migration that created it: DROP INDEX CONCURRENTLY "{index_name}";',
                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{index_name}";',
                ),
                caveats=[],
            )
        )

    return CheckResult(
        name="invalid_indexes",
        label="Invalid indexes",
        status="warning" if items else "ok",
        summary=str(len(items)) if items else "none",
        items=items,
        message="",
        tier="warning",
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
                        source, package, model_class, model_file = _table_info(
                            table_name, table_owners
                        )
                        app_suggestion = f'Remove "{name_s}" from model indexes/constraints, then run plain postgres sync'

                        items.append(
                            CheckItem(
                                table=table_name,
                                name=name_s,
                                detail=f"{size_s}, redundant with {name_l}",
                                source=source,
                                package=package,
                                model_class=model_class,
                                model_file=model_file,
                                suggestion=_index_suggestion(
                                    source=source,
                                    package=package,
                                    model_class=model_class,
                                    model_file=model_file,
                                    app_suggestion=app_suggestion,
                                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{name_s}";',
                                ),
                                caveats=[],
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
        tier="warning",
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
        source, package, model_class, model_file = _table_info(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=f"{table_name}.{column_name}",
                detail=f"references {referenced_table}",
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    model_class=model_class,
                    model_file=model_file,
                    app_suggestion=f'Add an Index on ["{column_name}"] to the model, then run plain postgres sync',
                    unmanaged_suggestion=f'CREATE INDEX CONCURRENTLY ON "{table_name}" ("{column_name}");',
                ),
                caveats=[],
            )
        )

    return CheckResult(
        name="missing_fk_indexes",
        label="Missing FK indexes",
        status="warning" if items else "ok",
        summary=str(len(items)) if items else "none",
        items=items,
        message="",
        tier="warning",
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
        source, package, model_class, model_file = _table_info(table_str, table_owners)
        items.append(
            CheckItem(
                table=table_str,
                name=f"{table_str}.{column_name}",
                detail=f"{data_type}, {pct_used}% used ({current_value:,} / {max_value:,})",
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=f'ALTER TABLE "{table_str}" ALTER COLUMN "{column_name}" SET DATA TYPE bigint;',
                caveats=[],
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
        tier="warning",
    )
