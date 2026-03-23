---
labels:
  - plain-postgres
related:
  - models-non-blocking-ddl
  - migrations-schema-check
  - postgres-cli-and-insights
---

# Migration safety analysis

## Problem

Database migrations can cause downtime, data loss, or performance degradation — but Plain doesn't warn about any of this. A developer runs `makemigrations`, gets a migration file, runs `migrate`, and hopes for the best. If the migration takes an ACCESS EXCLUSIVE lock on a large table, blocks writes for 10 minutes, or rewrites the entire table, they find out in production.

This is preventable. The dangerous patterns are well-known and detectable by analyzing the SQL a migration generates.

## Industry context

**squawk** ([squawkhq.com](https://squawkhq.com/)) is a Postgres migration linter that catches dangerous patterns in SQL. It's widely used in the Rails and Django ecosystems. Their rule set is the gold standard for what to check.

**django-pg-migration-tools** provides safe alternatives (`SaferAddUniqueConstraint`, etc.) but doesn't detect when you're using the unsafe versions.

Plain is in a unique position: it owns the migration system AND knows it's Postgres-only. It can analyze migrations at the operation level (not just raw SQL) and provide framework-specific guidance.

## What to detect

### Blocking operations (cause downtime on large tables)

| Operation                                     | Risk                                           | What happens                                   | Safe alternative                                                                                      |
| --------------------------------------------- | ---------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `CREATE INDEX` (non-concurrent)               | SHARE lock blocks writes                       | Writes queue until index build finishes        | `CREATE INDEX CONCURRENTLY`                                                                           |
| `ALTER TABLE ADD CONSTRAINT UNIQUE`           | ACCESS EXCLUSIVE lock                          | Blocks all reads and writes                    | Create index concurrently, then add constraint using index                                            |
| `ALTER TABLE ADD CONSTRAINT FK`               | SHARE ROW EXCLUSIVE on both tables + full scan | Blocks writes on both source and target tables | `ADD CONSTRAINT FK NOT VALID` then `VALIDATE CONSTRAINT`                                              |
| `ALTER TABLE ADD CONSTRAINT CHECK`            | ACCESS EXCLUSIVE + full scan                   | Blocks everything                              | `ADD CONSTRAINT CHECK NOT VALID` then `VALIDATE CONSTRAINT`                                           |
| `ALTER TABLE SET NOT NULL` on existing column | Full table scan under ACCESS EXCLUSIVE         | Blocks everything while scanning all rows      | Add CHECK constraint NOT VALID, validate, then set NOT NULL (PG 12+ skips scan if valid CHECK exists) |

### Data-rewriting operations (slow on large tables)

| Operation                                       | Risk                           | What happens                                                                                                     |
| ----------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `ALTER TABLE ALTER COLUMN TYPE`                 | Full table rewrite             | Entire table is rewritten. On a 100GB table, this takes a long time under ACCESS EXCLUSIVE lock.                 |
| `ALTER TABLE ADD COLUMN ... DEFAULT` (volatile) | Full table rewrite (pre-PG 11) | PG 11+ handles static defaults without rewrite, but volatile defaults (e.g., `gen_random_uuid()`) still rewrite. |

### Destructive operations

| Operation                     | Risk                                             |
| ----------------------------- | ------------------------------------------------ |
| `DROP TABLE` / `DROP COLUMN`  | Permanent data loss                              |
| `ALTER TABLE DROP CONSTRAINT` | May allow invalid data to enter                  |
| Renaming tables or columns    | Breaks application code that hasn't been updated |

### Potentially dangerous patterns

| Pattern                                     | Risk                                         |
| ------------------------------------------- | -------------------------------------------- |
| Adding NOT NULL column without default      | Fails on non-empty tables                    |
| Adding column with volatile default         | Table rewrite                                |
| Backfill in same migration as schema change | Runs under the same lock, extending downtime |

## Implementation

### When to check

**Option A: `makemigrations` warns**

When generating migrations, print warnings alongside the migration file:

```
$ plain makemigrations

Migrations for 'myapp':
  myapp/migrations/0042_add_email_index.py
    - Create index myapp_user_email_idx on myapp.User

  ⚠  WARNING: CreateIndex on a non-empty table acquires a SHARE lock (blocks writes).
     Consider using concurrently=True for zero-downtime deployment.
     See: https://plainframework.com/docs/plain-postgres/migrations#concurrent-indexes
```

**Option B: `migrate` warns before applying**

Before applying a migration, analyze it and warn:

```
$ plain migrate

Pending migrations:
  [1] myapp/0042_add_email_index.py

  ⚠  This migration contains operations that may cause downtime:
     - CreateIndex without CONCURRENTLY (blocks writes)

  Apply? [y/n]:
```

**Option C: Preflight check**

`plain check` analyzes pending migrations and warns about unsafe operations. This runs in CI and at deploy time.

**Recommendation**: Do all three. Warn at generation time (so developers learn), warn before apply (last chance to abort), and check in CI (catch it in review).

### What to analyze

Each migration operation maps to known SQL patterns. The analysis doesn't need to parse SQL — it can inspect the operation objects directly:

```python
for operation in migration.operations:
    if isinstance(operation, AddIndex) and not operation.concurrently:
        if table_has_rows(operation.model_name):
            warn("CreateIndex without CONCURRENTLY blocks writes")

    if isinstance(operation, AddConstraint):
        constraint = operation.constraint
        if isinstance(constraint, UniqueConstraint) and not operation.concurrently:
            warn("Adding unique constraint acquires ACCESS EXCLUSIVE lock")
```

### Table size awareness

Some operations are fine on small/empty tables but dangerous on large ones. The analysis should be size-aware:

- Empty table (initial migration): Skip all warnings — no lock contention possible
- Small table (<10K rows): Lower severity warnings
- Large table (>100K rows): Full warnings
- Very large table (>1M rows): Elevated severity

This requires a database connection during analysis (to check `pg_stat_user_tables` or `information_schema`). For `makemigrations` (which may not have DB access), fall back to warning regardless of size.

## What this connects to

- **`models-non-blocking-ddl`** — Provides the safe alternatives that this analysis recommends
- **`migrations-schema-check`** — Post-migration drift detection (complementary — this is pre-migration)
- **`postgres-cli-and-insights`** — The `diagnose` command checks runtime state; this checks migration safety

## Open questions

1. **Should unsafe operations be errors or warnings?** Warnings are less disruptive but can be ignored. Errors force action but may frustrate developers in development (where lock contention doesn't matter). Maybe warnings by default, errors in CI/production via a flag.
2. **Should Plain auto-fix?** If it detects `AddIndex` without `concurrently`, should it offer to rewrite the migration? Or just warn and link to docs?
3. **How to handle custom `RunSQL` operations?** The analysis can inspect Plain's operation classes, but `RunSQL` is opaque. Could optionally parse the SQL with a linter like squawk's rules.
4. **Should there be a `# safe: ignore` comment** to suppress specific warnings for cases where the developer knows better?

## References

- [squawk](https://squawkhq.com/) — Postgres migration linter, comprehensive rule set
- [django-pg-migration-tools](https://django-pg-migration-tools.readthedocs.io/) — Safe migration alternatives for Django
- [strong_migrations](https://github.com/ankane/strong_migrations) — Ruby gem that catches dangerous migrations (Rails equivalent)
