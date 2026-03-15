---
labels:
  - plain-postgres
---

# Rename `app` column to `package` in plainmigrations table

The `plainmigrations` table has an `app` column — a legacy Django term. In Plain it should be `package` to match `package_label`.

## What changes

- Model field in `recorder.py`: `app` → `package`
- All references: `migration.app`, `.filter(app=...)`, `record_applied(app=...)`, etc.
- DB column: `ALTER TABLE plainmigrations RENAME COLUMN app TO package`

## Approach

The `plainmigrations` table is manually managed (not via migrations) — it's the chicken-and-egg table. Currently `ensure_schema()` only checks if the table exists, never updates its schema.

Use simple inline column checks in `ensure_schema()` — introspect actual columns, rename if needed. No versioning framework, just explicit checks. This table changes maybe once every few years.

```python
def ensure_schema(self):
    if self.has_table():
        with self.connection.cursor() as cursor:
            columns = {col.name for col in self.connection.introspection.get_table_description(cursor, MIGRATION_TABLE_NAME)}
            if "app" in columns and "package" not in columns:
                cursor.execute(f'ALTER TABLE {MIGRATION_TABLE_NAME} RENAME COLUMN app TO package')
        return
    # ... create table as before
```
