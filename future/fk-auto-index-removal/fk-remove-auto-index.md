---
depends_on:
  - remove-index-auto-naming
related:
  - ../postgres-insights/preflight-index-checks
---

# Remove auto-indexing on ForeignKey fields

Done. `db_index` parameter fully removed from `ForeignKeyField`. FK fields create no indexes on their own — declare an explicit `Index(fields=["field"], name="...")`.

## What was done

1. Removed `db_index` parameter from `ForeignKeyField.__init__` entirely
2. Removed `db_index` from `deconstruct()`
3. Removed `_field_should_be_indexed` (always returned `False`, now deleted)
4. Removed db_index add/remove blocks from `_alter_field` in schema editor
5. Removed `db_index` skip in `CheckMissingFKIndexes` preflight
6. Removed auto FK index collection from `_collect_model_indexes` preflight helper
7. Simplified Postgres-specific like-index blocks to primary-key-only
8. Added explicit FK indexes to 4 uncovered framework packages (oauth, support, redirection, observer)
9. Migration files use `DROP INDEX IF EXISTS "old_auto_name"` + `AddIndex` to handle orphan cleanup

## Upgrade path

The `/plain-upgrade` skill should:

1. For each FK field, check if covered by a declared `Index` or `UniqueConstraint`
2. **If uncovered**: add `Index(fields=["field"], name="table_column_idx")`, generate `RunSQL('DROP INDEX IF EXISTS "old_auto_name"')` + `AddIndex`
3. **If covered**: generate `RunSQL('DROP INDEX IF EXISTS "old_auto_name"')` to clean up the redundant orphan
4. Remove any `db_index=False` from FK fields and migration files (parameter no longer exists)

Old auto-index names reconstructed via `_create_index_name` / `names_digest` — deterministic.
