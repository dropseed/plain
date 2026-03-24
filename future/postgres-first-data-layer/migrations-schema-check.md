---
related:
  - migrations-rename-app-column
---

# migrations: Schema drift detection

Since Plain fully owns the database schema (no unmanaged models, no `inspectdb`, no coexisting with external schema management), the current model definitions are the single source of truth. If a column's actual type doesn't match `field.db_type()`, it's wrong — there's no "intentional divergence" to account for.

This means schema drift detection can be a straightforward preflight check: compare model definitions against the real DB and error on any mismatch.

## Motivation

We hit a `DataError: value too long for type character varying(64)` on an `EncryptedTextField(max_length=64)` field. The migration that added it had been faked — so the column was `varchar(64)` (from an earlier manual step) instead of `text` (what `db_type()` returns). Nothing caught this. `migrations make --check` only compares models against migration files, not against the actual DB.

A preflight check would have surfaced this immediately at startup or deploy time, before the runtime error.

## Approach

Start with a standalone command: `plain migrations check-schema`. It's a diagnostic tool — reports what's different between model definitions and the actual DB, and the user decides how to act on it.

This avoids making upfront decisions about what constitutes "wrong" vs "intentional." A manually-added index, an extra column from a mid-rollout migration, a type mismatch from a faked migration — the command reports all of them the same way. The user interprets the results.

If patterns emerge (e.g. column type mismatches are always bugs), specific checks could later be promoted to preflight errors. But the command comes first.

### What it compares

For each model, compare expected state (from `field.db_type()`, `field.column`, `field.allow_null`, etc.) against actual DB state via `information_schema`:

- **Column types**: `field.db_type()` vs actual `data_type` / `character_maximum_length`
- **Nullability**: `field.allow_null` vs actual `is_nullable`
- **Missing columns**: field exists in model but not in DB table
- **Extra columns**: column in DB but not in model
- **Indexes and constraints**: expected vs actual

### Example output

```
$ plain migrations check-schema

organizations.Organization
  gitlab_webhook_secret:
    expected: text
    actual:   character varying(64)

  15 columns, 3 indexes, 2 constraints checked
  1 mismatch

All other models OK.
```

## Open questions

- Should the output suggest fixes? e.g. "Run: ALTER TABLE ... ALTER COLUMN ... TYPE text" — useful since type mismatches are always a one-liner.
- Should there be a `--exit-code` flag (or similar) so CI can use it as a gate?
- Over time, which mismatches (if any) should graduate to preflight errors? Column type mismatches seem like strong candidates — there's no good reason for those. Extra columns/indexes are more ambiguous.
