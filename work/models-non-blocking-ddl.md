---
labels:
  - plain-postgres
related:
  - models-index-suggestions
---

# Non-blocking DDL for indexes, constraints, and foreign keys

## Problem

Several common migration operations acquire heavy locks that block writes (or all access) for the duration of the operation. On large tables this can take minutes or hours, causing downtime. PostgreSQL provides non-blocking alternatives for each, but Plain doesn't use any of them.

| Operation                           | Default lock                                           | Duration on large tables | Non-blocking alternative                                                  |
| ----------------------------------- | ------------------------------------------------------ | ------------------------ | ------------------------------------------------------------------------- |
| `CREATE INDEX`                      | SHARE (blocks writes)                                  | Minutes–hours            | `CREATE INDEX CONCURRENTLY`                                               |
| `CREATE UNIQUE INDEX`               | SHARE (blocks writes)                                  | Minutes–hours            | `CREATE UNIQUE INDEX CONCURRENTLY`                                        |
| `ALTER TABLE ADD CONSTRAINT UNIQUE` | ACCESS EXCLUSIVE (blocks everything)                   | Brief but exclusive      | Create index concurrently first, then `ADD CONSTRAINT UNIQUE USING INDEX` |
| `ALTER TABLE ADD CONSTRAINT FK`     | SHARE ROW EXCLUSIVE on **both** tables + full row scan | Minutes–hours            | `ADD CONSTRAINT FK NOT VALID` then `VALIDATE CONSTRAINT`                  |
| `ALTER TABLE ADD CONSTRAINT CHECK`  | ACCESS EXCLUSIVE + full row scan                       | Minutes–hours            | `ADD CONSTRAINT CHECK NOT VALID` then `VALIDATE CONSTRAINT`               |

Plain already has the SQL templates for concurrent index creation/deletion, but nothing in the migration system actually uses them. There is no support at all for `NOT VALID` / `VALIDATE CONSTRAINT`.

## Current state

### What exists

The schema editor has SQL templates and plumbing for regular (non-unique) indexes:

```python
# Schema editor SQL templates (postgres/schema.py)
sql_create_index_concurrently = "CREATE INDEX CONCURRENTLY ..."
sql_delete_index_concurrently = "DROP INDEX CONCURRENTLY IF EXISTS ..."

# Schema editor methods accept concurrently parameter
def add_index(self, model, index, concurrently=False)
def remove_index(self, model, index, concurrently=False)

# _create_index_sql selects template based on concurrently flag
def _create_index_sql(self, ..., concurrently=False)
def _delete_index_sql(self, ..., concurrently=False)
```

### What's missing

1. **No migration operations use it.** `AddIndex` and `RemoveIndex` never pass `concurrently=True` to the schema editor.

2. **No unique index concurrent support.** There is no `sql_create_unique_index_concurrently` template, and `_create_unique_sql` / `_delete_unique_sql` don't accept a `concurrently` parameter. This means `UniqueConstraint` (when backed by `CREATE UNIQUE INDEX`) can't be created concurrently.

3. **No tests** for any concurrent behavior.

### How UniqueConstraint works (two modes)

UniqueConstraint generates different SQL depending on its parameters:

| Parameters                                                | SQL generated                                     | Could use CONCURRENTLY?     |
| --------------------------------------------------------- | ------------------------------------------------- | --------------------------- |
| Simple `fields` only                                      | `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE (...)` | No — not an index operation |
| Has `expressions`, `condition`, `include`, or `opclasses` | `CREATE UNIQUE INDEX ...`                         | Yes                         |

The decision happens in `_unique_sql()` / `_create_unique_sql()` based on whether any of those advanced parameters are set.

### Foreign key creation (no support)

Adding a FK with `ALTER TABLE ADD CONSTRAINT FOREIGN KEY` takes a `SHARE ROW EXCLUSIVE` lock on **both** the source and target tables, then does a full table scan to validate all existing rows. Adding a FK to anything that references a large, heavily-written table (like `users`) blocks writes to both tables for the duration of the scan.

PostgreSQL's two-step alternative:

1. `ALTER TABLE ADD CONSTRAINT fk ... NOT VALID` — adds the constraint to the catalog (new inserts/updates are validated immediately) but skips the existing-row scan. Brief lock only.
2. `ALTER TABLE VALIDATE CONSTRAINT fk` — scans existing rows with a weaker lock (`SHARE UPDATE EXCLUSIVE` on source, `ROW SHARE` on target). Allows concurrent writes to both tables.

This is arguably more impactful than index CONCURRENTLY because it locks two tables and FK additions are extremely common (every `ForeignKeyField` migration).

Plain has zero support for this. Django only has `AddConstraintNotValid` / `ValidateConstraint` for CHECK constraints — not FKs (guarded by `isinstance(constraint, CheckConstraint)`).

### CHECK constraint creation (no support)

Same pattern as FK — `ALTER TABLE ADD CONSTRAINT CHECK` takes ACCESS EXCLUSIVE + full scan. `NOT VALID` + `VALIDATE CONSTRAINT` avoids both.

### The transaction problem

`CREATE INDEX CONCURRENTLY` and `VALIDATE CONSTRAINT` cannot run inside a transaction block. Today:

- Each migration runs in a transaction by default (`Migration.atomic = True`)
- The schema editor's `__enter__` starts an `atomic()` block when `atomic_migration=True`
- Both `CONCURRENTLY` and `VALIDATE CONSTRAINT` would fail inside this transaction

### Failure modes

These non-blocking patterns trade atomicity for availability. The failure scenarios are important:

**INVALID indexes from failed CONCURRENTLY:**

- If `CREATE INDEX CONCURRENTLY` fails (timeout, deadlock, duplicate key), it leaves an INVALID index
- The INVALID index still imposes write overhead — Postgres maintains it on every insert/update
- Queries won't use it
- You must `DROP INDEX` it before retrying
- Re-running the migration without handling this hits "index already exists"
- The migration system needs either `IF NOT EXISTS` or detection/cleanup logic

**Long-running transactions stall CONCURRENTLY:**

- `CONCURRENTLY` waits for ALL existing transactions that reference the table to finish
- A single forgotten open transaction or long-running query can stall it indefinitely
- If it times out or deadlocks during this wait, you get the INVALID index above

**Partial migration failure (non-atomic migrations):**

- If a migration has 3 operations and you break out of the transaction for a concurrent op, and then operation 3 fails:
    - Operations 1 and 2 are committed, can't roll back
    - The migration is recorded as not applied
    - Re-running tries to re-apply ops 1 and 2, which fail or duplicate
    - You're stuck in a manually-recoverable state
- This is why Django recommends putting concurrent operations in their own migration file
- For `NOT VALID` + `VALIDATE`, the two steps should also be in separate migrations

**Resource cost:**

- `CONCURRENTLY` does two full table scans instead of one, and waits for existing transactions between them
- The overall operation takes longer — it's non-blocking but slower
- `VALIDATE CONSTRAINT` also does a full scan, just with a weaker lock

## How Django handles this

Django has separate operation classes in `contrib.postgres`:

```python
class AddIndexConcurrently(NotInTransactionMixin, AddIndex):
    atomic = False  # prevents transaction wrapping for this operation

    def database_forwards(self, ...):
        self._ensure_not_in_transaction(schema_editor)  # raises if in transaction
        schema_editor.add_index(model, self.index, concurrently=True)
```

The user must set `atomic = False` on the entire migration class. This removes transactional safety from every other operation in that migration, so Django recommends putting concurrent operations in their own migration file.

Django does **not** have `AddConstraintConcurrently` — that's what [django/new-features#124](https://github.com/django/new-features/issues/124) is proposing.

## Design options

### Option A: Always use non-blocking DDL (automatically)

The schema editor would automatically use CONCURRENTLY for indexes and NOT VALID + VALIDATE for FKs/CHECKs. Initial migrations on empty tables could skip this since there's no lock contention.

**Pros:**

- Zero configuration — users never accidentally lock a table
- Simpler mental model
- Matches what you'd want in production 99% of the time

**Cons:**

- Index creation can't be rolled back if a later operation in the migration fails
- Failed concurrent builds leave an `INVALID` index that needs manual cleanup
- Complex transaction management — committing mid-migration, re-opening transactions
- Only applies to index-backed operations (not `ALTER TABLE ... ADD CONSTRAINT UNIQUE`)
- Every user is exposed to the failure modes above by default

### Option B: `concurrently` parameter on existing operations

```python
migrations.AddIndex(
    model_name="mymodel",
    index=models.Index(fields=["email"], name="mymodel_email_idx"),
    concurrently=True,
)

migrations.AddConstraint(
    model_name="mymodel",
    constraint=models.UniqueConstraint(
        Lower("email"), name="uniq_email_ci",
    ),
    concurrently=True,
)
```

The operation sets `atomic = False` on itself and handles the transaction boundary.

**Pros:**

- Explicit — clear when concurrent behavior is used
- Works with existing migration framework
- Can raise a clear error if used on a non-index-backed constraint

**Cons:**

- Users have to know to use it
- Mixed migrations (concurrent + non-concurrent ops) need care

### Option C: Separate operation classes (Django's approach)

```python
migrations.AddIndexConcurrently(...)
migrations.AddConstraintConcurrently(...)
```

**Pros:** Very explicit, easy to grep for.
**Cons:** More API surface, feels heavy for a PostgreSQL-only framework.

## What needs to change

### Index CONCURRENTLY

1. Add `sql_create_unique_index_concurrently` and `sql_delete_unique_index_concurrently` templates
2. Add `concurrently` parameter to `_create_unique_sql()` and `_delete_unique_sql()`
3. Add `concurrently` parameter to `UniqueConstraint.create_sql()` and `remove_sql()`
4. Add `concurrently` parameter to `add_constraint()` and `remove_constraint()` on the schema editor
5. Handle transaction boundary — either per-operation `atomic = False` or automatic commit/re-open
6. Error if `concurrently=True` on a constraint that uses `ALTER TABLE` (not index-backed)
7. Handle INVALID index cleanup on failure (detect existing INVALID indexes, offer to drop and retry)
8. Tests

### FK / CHECK NOT VALID

1. Add `not_valid` parameter to FK and CHECK constraint creation in the schema editor
2. Add `VALIDATE CONSTRAINT` support to the schema editor
3. Migration operations that split constraint creation into two steps (add NOT VALID, then validate)
4. The two steps must be in separate migrations (validate can't be in the same transaction as the NOT VALID add)
5. Tests

## Open questions

- Should `makemigrations` ever generate non-blocking operations automatically?
- Should there be a preflight check warning about blocking DDL operations on large tables?
- For Option A: is losing transactional rollback for index operations acceptable? Should initial migrations be excluded?
- Could simple `UniqueConstraint(fields=...)` be changed to always use `CREATE UNIQUE INDEX` instead of `ALTER TABLE ADD CONSTRAINT`? That would unify the two modes and make CONCURRENTLY available for all unique constraints.
- Should FK NOT VALID be the default for all FK additions, or opt-in? FKs are the most common case and lock two tables.
- How should the migration system handle the two-step NOT VALID + VALIDATE pattern? Auto-generate two migrations, or require the user to create them separately?

## References

- [django/new-features#124](https://github.com/django/new-features/issues/124) — Proposal for `AddConstraintConcurrently` in Django
- [django-pg-migration-tools](https://django-pg-migration-tools.readthedocs.io/) — Third-party Django package for zero-downtime migrations (SaferAddUniqueConstraint, etc.)
