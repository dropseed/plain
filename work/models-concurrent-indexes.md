---
labels:
  - plain-models
related:
  - models-index-suggestions
---

# CONCURRENTLY support for index and constraint operations

## Problem

Creating or dropping indexes on large PostgreSQL tables acquires a `SHARE` lock that blocks all writes for the duration of the build. On large tables this can take minutes or hours, causing downtime. PostgreSQL's `CONCURRENTLY` option uses a lighter lock that allows reads and writes to continue.

Plain already has the SQL templates for concurrent index creation/deletion, but nothing in the migration system actually uses them.

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

### The transaction problem

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. Today:

- Each migration runs in a transaction by default (`Migration.atomic = True`)
- The schema editor's `__enter__` starts an `atomic()` block when `atomic_migration=True`
- CONCURRENTLY would fail inside this transaction

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

### Option A: Always use CONCURRENTLY (automatically)

The schema editor would automatically break out of the transaction for index DDL and always use CONCURRENTLY. Initial migrations on empty tables could skip this since there's no lock contention.

**Pros:**

- Zero configuration — users never accidentally lock a table
- Simpler mental model
- Matches what you'd want in production 99% of the time

**Cons:**

- Index creation can't be rolled back if a later operation in the migration fails
- Failed concurrent builds leave an `INVALID` index that needs manual cleanup
- Complex transaction management — committing mid-migration, re-opening transactions
- Only applies to index-backed operations (not `ALTER TABLE ... ADD CONSTRAINT UNIQUE`)

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

Regardless of option chosen:

1. Add `sql_create_unique_index_concurrently` and `sql_delete_unique_index_concurrently` templates
2. Add `concurrently` parameter to `_create_unique_sql()` and `_delete_unique_sql()`
3. Add `concurrently` parameter to `UniqueConstraint.create_sql()` and `remove_sql()`
4. Add `concurrently` parameter to `add_constraint()` and `remove_constraint()` on the schema editor
5. Handle transaction boundary — either per-operation `atomic = False` or automatic commit/re-open
6. Error if `concurrently=True` on a constraint that uses `ALTER TABLE` (not index-backed)
7. Tests

## Open questions

- Should `makemigrations` ever generate concurrent operations automatically?
- Should there be a preflight check warning about non-concurrent index operations on large tables?
- For Option A: is losing transactional rollback for index operations acceptable? Should initial migrations be excluded?
- Could simple `UniqueConstraint(fields=...)` be changed to always use `CREATE UNIQUE INDEX` instead of `ALTER TABLE ADD CONSTRAINT`? That would unify the two modes and make CONCURRENTLY available for all unique constraints.
