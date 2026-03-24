# `plain postgres diagnose`

A single command that runs high-value checks against Postgres system catalogs and gives pass/fail results. This is the pattern every tool converges on (rails-pg-extras `diagnose`, Heroku `pg:diagnose`, Crunchy Bridge Production Check).

```
$ plain postgres diagnose

  Cache hit ratio          99.7%                  ✓
  Index hit ratio          99.9%                  ✓
  Unused indexes           2 (3.2 MB)             !  reviews_idx_old, tmp_migration_idx
  Duplicate indexes        none                   ✓
  Missing indexes          1 table                !  pullrequests_pullrequest (92% seq scans)
  Bloat                    normal                 ✓
  Long-running queries     none                   ✓
  Connections              12 active, 3 idle      ✓
  Sequence exhaustion      all OK                 ✓
  Vacuum health            all OK                 ✓

  8 passed, 2 warnings
```

Each check is a single SQL query. The work is in choosing thresholds and formatting output.

## Common high-value checks

Every tool implements these — they're the universal "worth checking" set:

| Check                | Source view                    | Threshold                       |
| -------------------- | ------------------------------ | ------------------------------- |
| Cache hit ratio      | `pg_statio_user_tables`        | ≥99%                            |
| Index hit ratio      | `pg_statio_user_indexes`       | ≥99%                            |
| Unused indexes       | `pg_stat_user_indexes`         | <50 scans, >1MB                 |
| Duplicate indexes    | `pg_index`, `pg_attribute`     | any                             |
| Missing indexes      | `pg_stat_user_tables`          | seq_scan >> idx_scan, >10k rows |
| Table/index bloat    | `pg_stat_user_tables`          | ≥10x ratio                      |
| Long-running queries | `pg_stat_activity`             | >1 min                          |
| Lock contention      | `pg_locks`, `pg_stat_activity` | blocking present                |
| Connection count     | `pg_stat_activity`             | near limit                      |
| Sequence exhaustion  | `pg_sequences`                 | >90% of type max                |
| TX ID wraparound     | `pg_database`                  | <10M remaining                  |
| Vacuum health        | `pg_stat_user_tables`          | dead tuples, last vacuum age    |

## Diagnostic SQL queries

Battle-tested queries from rails-pg-extras and [PlanetScale's database-skills](https://github.com/planetscale/database-skills/tree/main/skills/postgres/references):

**Unused indexes** (filters out expression indexes, unique indexes, and constraint-backing indexes):

```sql
SELECT s.relname AS table_name, s.indexrelname AS index_name,
  pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
FROM pg_catalog.pg_stat_user_indexes s
JOIN pg_catalog.pg_index i ON s.indexrelid = i.indexrelid
WHERE s.idx_scan = 0
  AND 0 <> ALL (i.indkey)       -- exclude expression indexes
  AND NOT i.indisunique          -- exclude UNIQUE indexes
  AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint c WHERE c.conindid = s.indexrelid)
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

**Invalid indexes** (failed `CREATE INDEX CONCURRENTLY` — maintained on every write, never used for reads):

```sql
SELECT indexrelname FROM pg_stat_user_indexes s
JOIN pg_index i ON s.indexrelid = i.indexrelid WHERE NOT i.indisvalid;
```

**Per-table index count** (>10 = significant write overhead, audit required):

```sql
SELECT relname AS table, count(*) as index_count
FROM pg_stat_user_indexes GROUP BY relname ORDER BY count(*) DESC;
```

**HOT update ratio** (target >90% on frequently updated tables):

```sql
SELECT relname, round(100.0 * n_tup_hot_upd / nullif(n_tup_upd, 0), 1) AS hot_pct
FROM pg_stat_user_tables WHERE n_tup_upd > 0 ORDER BY n_tup_upd DESC;
```

HOT (Heap-Only Tuple) updates skip all index maintenance when no indexed column value changes and free space exists on the page. Low HOT ratio on write-heavy tables suggests: too many indexes on frequently-updated columns, or `fillfactor` is too high (default 100%). Setting `fillfactor = 70-80` on write-heavy tables leaves room for in-place updates.

**Index bloat** (leaf density <70% = significant bloat):

```sql
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT avg_leaf_density FROM pgstatindex('my_index');
```

VACUUM removes dead tuples but does NOT reclaim empty index page space — only `REINDEX CONCURRENTLY` (PG 12+) or `pg_repack` compacts pages.

## XID wraparound

This is not a "warning" — it's a database-stopping emergency. If `age(datfrozenxid)` reaches ~2B, Postgres emergency-shuts down to prevent data corruption. Recovery requires single-user mode VACUUM that can take hours to days.

```sql
SELECT datname, age(datfrozenxid),
  ROUND(100.0 * age(datfrozenxid) / 2147483648, 2) AS pct_to_wraparound
FROM pg_database ORDER BY age(datfrozenxid) DESC;
```

Treat as critical (red) at >40% (~800M), warning at >25% (~500M).

## Index analysis knowledge

**Index selectivity**: A column's selectivity (COUNT DISTINCT / total rows) determines whether an index is worthwhile. Low selectivity (e.g., a boolean column with 2 values across 1M rows) usually makes poor indexes. Exception: highly skewed data (e.g., `is_pro` where only 4% are true).

**Duplicate index detection via left-most prefix rule**: An index on `(email, is_pro)` makes a standalone index on `(email)` redundant. The duplicate index check should detect this, not just exact duplicates.

**Index ordering matters for composites**: An index on `(a ASC, b ASC)` works for both-ASC and both-DESC queries (backward scan), but NOT for mixed-direction sorts `(a ASC, b DESC)`.

**Covering index opportunities**: When a query only selects columns that are all in an index, Postgres can do an index-only scan. Adding one column via `INCLUDE` could eliminate heap access.

## SARGable query awareness

Wrapping indexed columns in functions prevents index usage:

```sql
-- Bad: full table scan even with index on created_at
SELECT * FROM event WHERE date_trunc('day', created_at) = '2023-01-01';
-- Good: index scan
SELECT * FROM event WHERE created_at >= '2023-01-01' AND created_at < '2023-01-02';
```

## Open questions

- Should `diagnose` have `--json` output for CI pipelines?
- Which checks should have configurable thresholds vs. hardcoded sensible defaults?
