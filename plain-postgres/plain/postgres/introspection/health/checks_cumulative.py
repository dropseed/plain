"""Cumulative checks — depend on counters accumulated since the last
pg_stat_reset. Unreliable on freshly-reset clusters.

`check_stats_freshness`, `check_vacuum_health`, and `check_index_bloat`
are rendered as operational context (tier="operational") because the
remedy is DB-side (ANALYZE/VACUUM/REINDEX) and can't be expressed in
the user's model code today. `check_unused_indexes` and
`check_missing_index_candidates` stay in the warning tier because the
user can act on them by editing model indexes/constraints."""

from __future__ import annotations

from typing import Any

import psycopg.errors

from .helpers import (
    _display_path,
    _format_bytes,
    _index_suggestion,
    _pgss_usable,
    _top_queries_for_table,
)
from .ownership import _table_info
from .types import CheckItem, CheckResult, TableOwner


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
        source, package, model_class, model_file = _table_info(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=index_name,
                detail=f"{index_size}, 0 scans",
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=_index_suggestion(
                    source=source,
                    package=package,
                    model_class=model_class,
                    model_file=model_file,
                    app_suggestion=f'Remove "{index_name}" from model indexes/constraints, then run plain postgres sync',
                    unmanaged_suggestion=f'DROP INDEX CONCURRENTLY "{index_name}";',
                ),
                caveats=[],
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
        tier="warning",
    )


def check_vacuum_health(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Tables with significant dead tuple accumulation."""
    # NULLIF guards the division: rows with n_live_tup=0 produce NULL for
    # the ratio, which fails the >10 comparison and is excluded. Belt and
    # suspenders — WHERE predicate order isn't guaranteed to short-circuit.
    cursor.execute("""
        SELECT
            relname AS table_name,
            n_dead_tup,
            ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup, 0), 2) AS dead_tuple_pct,
            last_autovacuum
        FROM pg_catalog.pg_stat_user_tables
        WHERE n_live_tup > 0
          AND n_dead_tup > 1000
          AND 100.0 * n_dead_tup / NULLIF(n_live_tup, 0) > 10
        ORDER BY n_dead_tup DESC
        LIMIT 100
    """)
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    for table_name, n_dead, dead_pct, last_vacuum in rows:
        vacuum_info = str(last_vacuum)[:19] if last_vacuum else "never"
        source, package, model_class, model_file = _table_info(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=table_name,
                detail=f"{n_dead:,} dead tuples ({dead_pct}% of live), last vacuum: {vacuum_info}",
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=(
                    f'Run VACUUM (ANALYZE) "{table_name}"; to reclaim dead '
                    "tuples immediately. If this recurs, tune per-table "
                    "autovacuum_vacuum_scale_factor or investigate why "
                    "autovacuum is being starved (long-running "
                    "transactions, write volume)."
                ),
                caveats=[],
            )
        )

    return CheckResult(
        name="vacuum_health",
        label="Vacuum health",
        status="warning" if items else "ok",
        summary=f"{len(items)} tables need attention" if items else "all ok",
        items=items,
        message="",
        tier="operational",
    )


def check_index_bloat(cursor: Any, table_owners: dict[str, TableOwner]) -> CheckResult:
    """Indexes with significant estimated wasted space.

    Uses the ioguix btree-bloat estimator (same heuristic as pghero) to
    estimate wasted bytes per index. The estimator is approximate — it
    compares actual pages to the number required by the average tuple size
    from pg_statistic. Accuracy drops on tables with atypical distributions,
    but it's been battle-tested and flags real problems in practice.

    Only considers btree indexes; other AMs (gin, gist, hash, brin) have
    different bloat characteristics and aren't covered here. Partial
    indexes are included but estimated using full-table column widths
    from pg_stats (not filtered by the predicate), which tends to
    underreport actual bloat on highly selective partial indexes.

    Threshold: 10 MB wasted bytes. pghero's default is 100 MB for
    enterprise apps; we default lower because Plain targets apps across a
    wider size range, and 10 MB of bloat on a small DB is usually worth
    knowing about.
    """
    min_bloat_bytes = 10 * 1024 * 1024  # 10 MB

    # Cheap pre-check: if no public-schema btree index is even large enough
    # to plausibly contain 10 MB of bloat, skip the expensive estimator.
    # Scope must match the estimator's WHERE nspname = 'public' or large
    # catalog/extension indexes would defeat the fast-exit.
    cursor.execute(
        """
        SELECT 1
        FROM pg_class c
        JOIN pg_am am ON c.relam = am.oid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'i'
          AND am.amname = 'btree'
          AND n.nspname = 'public'
          AND c.relpages * current_setting('block_size')::bigint >= %(min)s
        LIMIT 1
        """,
        {"min": min_bloat_bytes},
    )
    if not cursor.fetchone():
        return CheckResult(
            name="index_bloat",
            label="Index bloat",
            status="ok",
            summary="none",
            items=[],
            message="",
            tier="operational",
        )

    # The bloat estimator joins pg_stats and can fail on tables that have
    # never been analyzed. Probe inside psycopg's `transaction()` so that
    # failure rolls back cleanly without affecting later checks.
    bloat_sql = """
        WITH btree_index_atts AS (
            SELECT
                nspname, relname, reltuples, relpages, indrelid, relam,
                regexp_split_to_table(indkey::text, ' ')::smallint AS attnum,
                indexrelid AS index_oid
            FROM pg_index
            JOIN pg_class ON pg_class.oid = pg_index.indexrelid
            JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
            JOIN pg_am ON pg_class.relam = pg_am.oid
            WHERE pg_am.amname = 'btree'
              AND nspname = 'public'
        ),
        index_item_sizes AS (
            SELECT
                i.nspname,
                i.relname,
                i.reltuples,
                i.relpages,
                i.relam,
                (quote_ident(s.schemaname) || '.' || quote_ident(s.tablename))::regclass AS starelid,
                a.attrelid AS table_oid,
                index_oid,
                current_setting('block_size')::numeric AS bs,
                CASE
                    WHEN version() ~ 'mingw32' OR version() ~ '64-bit' THEN 8
                    ELSE 4
                END AS maxalign,
                24 AS pagehdr,
                CASE WHEN max(coalesce(s.null_frac, 0)) = 0
                    THEN 2 ELSE 6
                END AS index_tuple_hdr,
                sum((1 - coalesce(s.null_frac, 0)) * coalesce(s.avg_width, 2048)) AS nulldatawidth
            FROM pg_attribute AS a
            JOIN pg_stats AS s
                ON (quote_ident(s.schemaname) || '.' || quote_ident(s.tablename))::regclass = a.attrelid
                AND s.attname = a.attname
            JOIN btree_index_atts AS i
                ON i.indrelid = a.attrelid AND a.attnum = i.attnum
            WHERE a.attnum > 0
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
        ),
        index_aligned AS (
            SELECT
                maxalign, bs, nspname,
                relname AS index_name,
                reltuples, relpages, relam, table_oid, index_oid,
                (2 +
                    maxalign - CASE
                        WHEN index_tuple_hdr %% maxalign = 0 THEN maxalign
                        ELSE index_tuple_hdr %% maxalign
                    END
                    + nulldatawidth + maxalign - CASE
                        WHEN nulldatawidth::integer %% maxalign = 0 THEN maxalign
                        ELSE nulldatawidth::integer %% maxalign
                    END
                )::numeric AS nulldatahdrwidth,
                pagehdr
            FROM index_item_sizes
        ),
        otta_calc AS (
            SELECT
                bs, nspname, table_oid, index_oid, index_name, relpages,
                coalesce(
                    ceil((reltuples * (4 + nulldatahdrwidth)) / (bs - pagehdr::float)) +
                    CASE WHEN am.amname IN ('hash', 'btree') THEN 1 ELSE 0 END,
                    0
                ) AS otta
            FROM index_aligned AS s2
            LEFT JOIN pg_am am ON s2.relam = am.oid
        ),
        raw_bloat AS (
            SELECT
                nspname,
                c.relname AS table_name,
                index_name,
                bs * sub.relpages::bigint AS totalbytes,
                CASE WHEN sub.relpages <= otta THEN 0
                    ELSE bs * (sub.relpages - otta)::bigint END AS wastedbytes,
                CASE WHEN sub.relpages <= otta THEN 0
                    ELSE (bs * (sub.relpages - otta)::bigint * 100)
                         / NULLIF(bs * sub.relpages::bigint, 0) END AS realbloat,
                stat.indexrelid
            FROM otta_calc AS sub
            JOIN pg_class AS c ON c.oid = sub.table_oid
            JOIN pg_stat_user_indexes AS stat ON sub.index_oid = stat.indexrelid
        )
        SELECT
            table_name,
            index_name,
            wastedbytes,
            totalbytes,
            realbloat,
            i.indisprimary
        FROM raw_bloat rb
        JOIN pg_index i ON i.indexrelid = rb.indexrelid
        WHERE wastedbytes >= %(min)s
        ORDER BY wastedbytes DESC
    """
    try:
        with cursor.connection.transaction():
            cursor.execute(bloat_sql, {"min": min_bloat_bytes})
            rows = cursor.fetchall()
    except psycopg.errors.DatabaseError:
        return CheckResult(
            name="index_bloat",
            label="Index bloat",
            status="skipped",
            summary="could not estimate",
            items=[],
            message="Bloat estimator query failed (may require ANALYZE on target tables).",
            tier="operational",
        )
    items: list[CheckItem] = []
    for table_name, index_name, wasted, total, pct, is_primary in rows:
        source, package, model_class, model_file = _table_info(table_name, table_owners)
        pct_str = f"{float(pct):.0f}%" if pct is not None else "?%"
        primary_note = " (PRIMARY KEY)" if is_primary else ""
        if is_primary:
            fix = (
                f'Requires care — REINDEX INDEX CONCURRENTLY "{index_name}"; '
                "on a PK rebuilds it without locking writes. Monitor locks."
            )
        else:
            fix = f'REINDEX INDEX CONCURRENTLY "{index_name}";'
        items.append(
            CheckItem(
                table=table_name,
                name=index_name,
                detail=(
                    f"{_format_bytes(wasted)} wasted ({pct_str} of "
                    f"{_format_bytes(total)}){primary_note}"
                ),
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=fix,
                caveats=[],
            )
        )

    return CheckResult(
        name="index_bloat",
        label="Index bloat",
        status="warning" if items else "ok",
        summary=f"{len(items)} indexes bloated" if items else "none",
        items=items,
        message="",
        tier="operational",
    )


def check_stats_freshness(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Tables whose planner statistics are missing or stale relative to activity.

    Stale stats cause the planner to make bad decisions and cause every other
    stat-based check (unused_indexes, vacuum_health, missing-index heuristics,
    slow-query analysis) to be less trustworthy. Autovacuum's default
    analyze trigger is 10% row modification; we flag at 25% as a signal it's
    falling behind, and always flag tables that have literally never been
    analyzed.
    """
    # pg_class.reltuples is the robust "never analyzed" signal: it's -1 until
    # ANALYZE runs and populates it, and pg_stat_reset() does NOT clear it
    # (pg_stat_reset only wipes the cumulative counters in pg_stat_*). Relying
    # on last_analyze/last_autoanalyze alone would falsely flag every table
    # after a stats reset even though pg_statistic is still populated.
    cursor.execute("""
        SELECT
            st.relname AS table_name,
            st.n_live_tup,
            st.n_mod_since_analyze,
            GREATEST(st.last_analyze, st.last_autoanalyze) AS last_any_analyze,
            pg_relation_size(st.relid) AS bytes,
            c.reltuples AS pg_class_reltuples
        FROM pg_catalog.pg_stat_user_tables st
        JOIN pg_catalog.pg_class c ON c.oid = st.relid
        WHERE st.schemaname = 'public'
    """)
    rows = cursor.fetchall()

    min_table_bytes = 1_000_000  # 1 MB — outer size floor for "worth flagging"
    min_mod_absolute = 1_000
    stale_churn_pct = 25.0

    items: list[CheckItem] = []
    for (
        table_name,
        n_live,
        n_mod,
        last_any_analyze,
        bytes_,
        pg_class_reltuples,
    ) in rows:
        n_live = n_live or 0
        n_mod = n_mod or 0
        bytes_ = bytes_ or 0

        # Skip trivially small tables with little activity — false-positive magnet.
        if bytes_ < min_table_bytes and n_mod < min_mod_absolute:
            continue

        reason = None
        detail = None

        truly_never_analyzed = pg_class_reltuples is not None and pg_class_reltuples < 0

        if truly_never_analyzed:
            # Inner threshold (10 MB) is intentionally stricter than the outer
            # (1 MB): never-analyzed tables produce suppressible-only noise on
            # small tables, but on larger tables or high-modification workloads
            # they directly skew planner choices.
            if n_mod >= min_mod_absolute or bytes_ >= 10_000_000:
                reason = "never analyzed"
                detail = (
                    f"never analyzed, table size {_format_bytes(bytes_)} "
                    f"— planner statistics are absent and n_live_tup is unreliable"
                )
        elif last_any_analyze is None:
            # pg_class.reltuples >= 0 but timestamps are gone → pg_stat_reset()
            # recently fired; pg_statistic is still valid, we just can't assess
            # freshness until counters repopulate. Skip rather than alarm.
            continue
        else:
            if n_live > 0 and n_mod >= min_mod_absolute:
                churn_pct = (n_mod / n_live) * 100
                if churn_pct >= stale_churn_pct:
                    reason = "stale"
                    age = str(last_any_analyze)[:19]
                    detail = (
                        f"{n_mod:,} tuples modified ({churn_pct:.1f}% churn) "
                        f"since last analyze at {age}"
                    )

        if reason is None:
            continue

        source, package, model_class, model_file = _table_info(table_name, table_owners)
        items.append(
            CheckItem(
                table=table_name,
                name=table_name,
                detail=detail or "",
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=(
                    f'Run ANALYZE "{table_name}"; to refresh planner statistics. '
                    "If this recurs, consider tuning per-table "
                    "autovacuum_analyze_scale_factor."
                ),
                caveats=[],
            )
        )

    return CheckResult(
        name="stats_freshness",
        label="Stats freshness",
        status="warning" if items else "ok",
        summary=f"{len(items)} tables have stale stats" if items else "all ok",
        items=items,
        message="",
        tier="operational",
    )


def check_missing_index_candidates(
    cursor: Any, table_owners: dict[str, TableOwner]
) -> CheckResult:
    """Tables whose sequential-scan activity suggests a missing index.

    Flags a table if either heuristic fires:

      A. pghero-style ratio — tables where a significant share of scans are
         sequential rather than indexed (catches tables with no usable index
         for their hot path).
      B. Rows-per-seq-scan — tables where each sequential scan reads many
         rows (catches tables with good coverage for most queries but a
         cold-path query doing expensive scans; pghero's ratio misses these).

    Uses pg_relation_size (not n_live_tup) for the size floor because
    n_live_tup is unreliable when ANALYZE hasn't run.

    When pg_stat_statements is installed, drills into the top contributing
    queries for each flagged table so the finding is actionable rather than
    "go investigate this table."
    """
    min_table_bytes = 10_000_000  # 10 MB
    ratio_threshold_pct = 5
    min_rows_per_seq_scan = 1_000
    min_seq_scans = 10

    pgss_state = _pgss_usable(cursor)
    pgss_usable = pgss_state == "usable"

    cursor.execute(
        """
        SELECT
            relname AS table_name,
            seq_scan,
            seq_tup_read,
            idx_scan,
            pg_relation_size(relid) AS table_bytes
        FROM pg_catalog.pg_stat_user_tables
        WHERE schemaname = 'public'
          AND pg_relation_size(relid) >= %(min_bytes)s
        """,
        {"min_bytes": min_table_bytes},
    )
    rows = cursor.fetchall()

    items: list[CheckItem] = []
    for table_name, seq_scan, seq_tup_read, idx_scan, bytes_ in rows:
        seq_scan = seq_scan or 0
        seq_tup_read = seq_tup_read or 0
        idx_scan = idx_scan or 0
        total_scans = seq_scan + idx_scan

        reasons: list[str] = []

        # Rule A — pghero-style ratio. Includes the idx_scan=0 case: a big
        # table with many seq scans and zero index scans is the clearest
        # possible sign that no index is serving the hot path.
        # (seq_scan >= min_seq_scans implies total_scans > 0.)
        if seq_scan >= min_seq_scans:
            seq_pct = 100.0 * seq_scan / total_scans
            if seq_pct > ratio_threshold_pct:
                reasons.append(
                    f"{seq_pct:.1f}% of scans are sequential "
                    f"({seq_scan:,} seq / {idx_scan:,} idx)"
                )

        # Rule B — amplification per seq scan.
        if seq_scan >= min_seq_scans:
            rows_per_seq = seq_tup_read // seq_scan
            if rows_per_seq >= min_rows_per_seq_scan:
                reasons.append(
                    f"{rows_per_seq:,} rows read per seq scan "
                    f"({seq_scan:,} scans, {seq_tup_read:,} tuples total)"
                )

        if not reasons:
            continue

        # Drill into the top contributing queries if pg_stat_statements is there.
        top_queries = (
            _top_queries_for_table(cursor, table_name, limit=3) if pgss_usable else []
        )
        if top_queries:
            query_lines = []
            for i, q in enumerate(top_queries, 1):
                query_lines.append(
                    f"    {i}. {q['blks_per_call']:,.0f} blks/call, "
                    f"{q['rows_per_call']} rows/call, "
                    f"{q['calls']:,} calls, {q['total_ms']:.0f}ms total"
                )
                query_lines.append(f"       {q['query'][:240]}")
            queries_detail = "\n  top queries:\n" + "\n".join(query_lines)
        elif pgss_state == "not_installed":
            queries_detail = "\n  (install pg_stat_statements for per-query drill-down)"
        elif pgss_state == "no_permission":
            queries_detail = (
                "\n  (pg_stat_statements is installed but this role cannot "
                "read it — grant pg_read_all_stats for per-query drill-down)"
            )
        else:
            queries_detail = (
                "\n  (pg_stat_statements is installed but has no matching "
                "queries yet — run production traffic or wait for stats to "
                "accumulate, then re-check)"
            )

        source, package, model_class, model_file = _table_info(table_name, table_owners)
        index_snippet = 'postgres.Index(name="...", fields=["..."])'
        # Suggestions reference "the top queries above" when we actually
        # printed some; otherwise point the user at the general workflow
        # (run pg_stat_statements / EXPLAIN against suspected hot queries).
        explain_lead = (
            "Run EXPLAIN on the top queries above"
            if top_queries
            else "Identify the queries hitting this table (pg_stat_statements, app logs, or slow-query log) and EXPLAIN them"
        )
        if model_class and model_file:
            suggestion = (
                f"{explain_lead}. If they share "
                f"WHERE/JOIN columns that aren't indexed, edit "
                f"{_display_path(model_file)} and add a {index_snippet} to "
                f"{model_class}.model_options, then `plain postgres sync`."
            )
        elif model_class:
            suggestion = (
                f"{explain_lead}. If they share "
                f"WHERE/JOIN columns that aren't indexed, add a "
                f"{index_snippet} to {model_class}.model_options "
                f"and run `plain postgres sync`."
            )
        elif source == "package":
            suggestion = f"Managed by {package} — report upstream if this persists."
        else:
            suggestion = (
                f"{explain_lead}. If they share "
                f"WHERE/JOIN columns that aren't indexed, add an index to "
                f'"{table_name}".'
            )

        items.append(
            CheckItem(
                table=table_name,
                name=table_name,
                detail=(
                    f"{_format_bytes(bytes_)}; " + "; ".join(reasons) + queries_detail
                ),
                source=source,
                package=package,
                model_class=model_class,
                model_file=model_file,
                suggestion=suggestion,
                caveats=[],
            )
        )

    items.sort(key=lambda it: it["table"])

    return CheckResult(
        name="missing_index_candidates",
        label="Missing index candidates",
        status="warning" if items else "ok",
        summary=f"{len(items)} tables flagged" if items else "none",
        items=items,
        message="",
        tier="warning",
    )


# Tier assignment lives in runner.py alongside ALL_CHECKS — see
# `_OPERATIONAL_CHECKS` there. Keeping it near the check list (rather than
# as function attributes) avoids the type-ignore dance and keeps both the
# ordering and the tier mapping in one place.
