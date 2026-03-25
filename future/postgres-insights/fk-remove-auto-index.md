---
related:
  - preflight-index-checks
---

# Remove auto-indexing on ForeignKey fields

Plain (inherited from Django) auto-creates an index on every ForeignKey column via `db_index=True` default. This leads to redundant indexes whenever a UniqueConstraint or composite Index starts with the same FK column — the FK auto-index is a prefix duplicate that Postgres maintains on every write but never uses for reads.

## The change

Remove `db_index` parameter from ForeignKeyField entirely. FK fields create no indexes on their own.

## Why this is safe

1. **Preflight check catches missing coverage** — a code-level preflight warning detects FK columns that aren't the leading column of any declared index or constraint (see `preflight-index-checks`)
2. **`plain db diagnose` catches DB-level gaps** — the missing FK indexes check queries the actual catalog
3. **Most FK columns are already covered** — by UniqueConstraints, composite indexes, or explicit indexes that users would declare anyway

## Why this is better

- No more redundant indexes from the framework (the `plain db diagnose` command found 8 in Plain's own example app, 16 on a production app)
- Developers are intentional about which FKs get indexed
- Explicit `Index(fields=["user"])` on a model is clearer than a hidden `db_index=True` default on the field class
- Fits Plain's philosophy: painfully obvious over clever

## Migration system limitation

**The migration system cannot automatically detect this change.** The `deconstruct()` method omits `db_index` when it matches the default. Since the old default was `True` and it was omitted, migration files never stored `db_index=True`. Changing the default (or removing the parameter) means the migration system reconstructs historical state with the NEW default, sees no difference, and generates no migrations.

The database still has the old auto-indexes from when the field was originally created. They become orphans — the migration system doesn't know about them, the model doesn't reference them.

This is a general Django/Plain limitation: **changing a field parameter's default silently reinterprets all historical migrations that omitted that parameter.** It's not a bug — it's a trade-off (clean migration files vs. safe default changes).

## Upgrade path

Because the migration system can't detect the change, the `/plain-upgrade` skill must handle the transition:

1. Find all FK fields in the user's app models
2. For each, check if it's covered by a declared index or constraint
3. For uncovered ones: add `Index(fields=["field_name"])` to the model
4. Generate an explicit migration that adds the new indexes
5. Generate a second migration (or include in the same one) that drops the old auto-indexes by name

The upgrade skill knows all FK fields had auto-indexes (since `db_index=True` was the universal default), so it can generate the cleanup without needing to inspect the database.

For Plain's own packages: create explicit migrations in each package that drop the redundant FK auto-indexes.

## Design decision: always index FK columns

Aligning with PlanetScale's database-skills guidance: **always index FK columns, no exceptions.**

The Postgres docs say "often a good idea... because this is not always needed" — but we're choosing the stricter rule because:

1. It's indisputable — no judgment calls about on_delete behavior or parent deletion frequency
2. The preflight check stays simple: missing FK index = warning, always
3. The diagnose `check_unused_indexes` already excludes sole-FK-coverage indexes from findings (even at 0 scans), so it won't contradict the preflight rule
4. Write overhead of a single B-tree index on a FK column is negligible compared to the risk of a seq scan + lock during an unexpected parent DELETE on a large table

**Key research finding**: FK enforcement scans (the RI trigger `SELECT ... FOR KEY SHARE` query) go through the normal Postgres executor and ARE counted in `pg_stat_user_indexes.idx_scan`. An FK index with `idx_scan = 0` truly has zero scans from all sources. But even so, we keep it — the index is insurance against future parent operations, and the cost of maintaining it is low.

This means the upgrade path (step 3) always adds explicit indexes for uncovered FK columns — no "is this one worth indexing?" analysis needed.

## Open questions

- Should we also remove auto-indexing from other relation fields (OneToOneField)?
- How to name the auto-indexes for cleanup? They follow the pattern `{table}_{column}_{hash}` — the upgrade skill needs to reconstruct these names to generate `RemoveIndex` operations.
- Should the upgrade skill generate one migration per app, or one per model?
