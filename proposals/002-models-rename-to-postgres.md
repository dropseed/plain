---
packages:
  - plain-models
related:
  - 001-db-connection-pool
---

# Rename `plain-models` to `plain-postgres`

## Why

`plain-models` is really a PostgreSQL package — it contains the ORM, the PostgreSQL backend, migrations, and connection management. There's no abstraction over multiple databases. The name should reflect that.

## What changes

### Package and imports

- PyPI package: `plain-models` → `plain-postgres` (or `plain.postgres`)
- Import path: `plain.models` → `plain.postgres` (or keep `plain.models` as a submodule?)
- Package label: `"plainmodels"` → `"plainpostgres"` (in `config.py`)

### Migration table

The `plainmigrations` table (defined in `recorder.py`) stores applied migrations with an `app` column containing the package label. Two concerns:

1. **Table name:** `plainmigrations` → rename or keep for backwards compatibility?
2. **`app` column values:** Existing rows reference package labels by their old names. If any package labels change, a data migration is needed to update the `app` column.

The `app` column currently stores whatever `package_label` each package's `PackageConfig` declares. The rename of `plain-models` itself doesn't affect user migration records (users' packages have their own labels), but if we rename the package label from `"plainmodels"` to `"plainpostgres"`, the special-case check in `loader.py:79` needs updating.

### Migration loader special case

`MigrationLoader.migrations_module()` (loader.py:79) returns `None` for the `"plainmodels"` package label since the migrations code is part of the package itself. This check needs to reference the new label.

### Files to update

- `plain-models/plain/models/config.py` — `package_label = "plainmodels"` → new label
- `plain-models/plain/models/migrations/recorder.py` — `MIGRATION_TABLE_NAME = "plainmigrations"` (keep or rename?)
- `plain-models/plain/models/migrations/loader.py` — special case for package label
- `plain-models/plain/models/migrations/migration.py` — docstrings reference `app_label`
- All `models-*` proposals — update `packages:` frontmatter
- The `/plain-upgrade` skill handles user import path changes

### Backwards compatibility

- The migration table name change needs a migration path: either keep the old name, or detect and rename the table automatically on first run.
- The `app` column values in existing `plainmigrations` rows are unaffected (they store user package labels, not the plain-models package label).
- Import path changes are handled by the upgrade agent.

## Open questions

- Does the import path change to `plain.postgres` or stay as `plain.models`? If `plain.models` stays, the rename is mostly cosmetic (PyPI name + package label).
- Should the migration table stay as `plainmigrations` forever? It's an internal detail users never see.
