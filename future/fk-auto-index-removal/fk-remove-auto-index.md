---
depends_on:
  - remove-index-auto-naming
related:
  - ../postgres-insights/preflight-index-checks
---

# Remove auto-indexing on ForeignKey fields

Remove `db_index` parameter from ForeignKeyField entirely. FK fields create no indexes on their own. If you want a FK column indexed, declare an explicit `Index(fields=["field"], name="...")`.

## Implementation

1. Remove `db_index` parameter from `ForeignKeyField.__init__` (keep as ignored kwarg with `False` default for migration file compatibility)
2. Remove `db_index` from `deconstruct()`
3. Set `self.db_index = False` unconditionally
4. Remove auto-indexing from schema editor (`_field_should_be_indexed` returns `False`)
5. Remove dead `db_index` handling in `_alter_field`
6. Remove `db_index` skip in `CheckMissingFKIndexes` preflight
7. Remove auto FK index collection from `_collect_model_indexes` preflight helper

**Verified**: `makemigrations --dry-run` detects no changes after this — historical migrations never stored `db_index=True`.

## Upgrade path

The `/plain-upgrade` skill:

1. For each FK field, check if covered by a declared `Index` or `UniqueConstraint`
2. **If uncovered**: add `Index(fields=["field"], name="table_column_idx")` to the model, generate `SeparateDatabaseAndState` to adopt the orphan auto-index into state and rename it (instant `ALTER INDEX RENAME`)
3. **If covered**: generate `RunSQL('DROP INDEX IF EXISTS "old_auto_name"')` to clean up the redundant orphan
4. Remove any `db_index=False` from FK fields (parameter no longer exists)

Old auto-index names reconstructed via `names_digest` — deterministic, verified.

## Design decision: always index FK columns

Aligning with PlanetScale's database-skills guidance: **always index FK columns, no exceptions.**

FK enforcement scans go through the normal Postgres executor and ARE counted in `pg_stat_user_indexes.idx_scan`. An FK index with `idx_scan = 0` truly has zero scans from all sources. But we keep it — insurance against future parent operations.

The preflight `missing_fk_indexes` check enforces this: any uncovered FK = warning. The diagnose `check_unused_indexes` excludes sole-FK-coverage indexes from findings.
