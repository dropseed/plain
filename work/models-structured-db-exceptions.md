---
labels:
- plain-models
related:
- models-db-level-on-delete
---

# Structured Database Exceptions

## Problem

When Postgres raises an integrity error, Plain surfaces a raw `IntegrityError` with an unparsed message string. Catching specific constraint violations (unique, FK, not-null, check) requires string parsing in user code.

## Proposal

Map Postgres error codes to specific exception classes:

```python
class ForeignKeyViolation(IntegrityError):
    """Referenced row still exists or doesn't exist (SQLSTATE 23503)"""
    table_name: str
    constraint_name: str
    detail: str

class UniqueViolation(IntegrityError):
    """Duplicate key value (SQLSTATE 23505)"""
    constraint_name: str
    detail: str

class NotNullViolation(IntegrityError):
    """NULL in a NOT NULL column (SQLSTATE 23502)"""
    column_name: str

class CheckViolation(IntegrityError):
    """CHECK constraint failed (SQLSTATE 23514)"""
    constraint_name: str
```

Postgres provides structured diagnostic fields via psycopg (`diag.constraint_name`, `diag.table_name`, `diag.column_name`, `diag.message_detail`), so these exceptions can be populated without string parsing.

## Postgres error codes

| SQLSTATE | Meaning               | Exception                        |
| -------- | --------------------- | -------------------------------- |
| `23503`  | Foreign key violation | `ForeignKeyViolation`            |
| `23505`  | Unique violation      | `UniqueViolation`                |
| `23502`  | Not null violation    | `NotNullViolation`               |
| `23514`  | Check violation       | `CheckViolation`                 |
| `23P01`  | Exclusion violation   | `ExclusionViolation` (if needed) |

## Use cases

**Unique constraint handling in views:**

```python
try:
    user.save()
except UniqueViolation as e:
    # e.constraint_name tells you exactly which constraint
    form.add_error("email", "Already taken")
```

**FK violation from DB-level ON DELETE RESTRICT:**

```python
try:
    author.delete()
except ForeignKeyViolation as e:
    # e.table_name, e.constraint_name, e.detail
    # all populated from Postgres diagnostics
    messages.error(request, f"Can't delete: referenced by {e.table_name}")
```

**Not-null violations:**

```python
try:
    post.save()
except NotNullViolation as e:
    # e.column_name tells you which field
    ...
```

## How other frameworks handle this

### Phoenix/Ecto

Ecto's `Repo.insert/update` returns `{:error, changeset}` with structured constraint errors. `unique_constraint/3` and `foreign_key_constraint/3` in changesets map DB errors to field-level messages. The pattern is declarative — you register which constraints map to which errors, and Ecto catches and wraps them automatically.

### Rails

ActiveRecord raises `ActiveRecord::RecordNotUnique` (wraps PG unique violation) and `ActiveRecord::InvalidForeignKey` (wraps FK violation). These are subclasses of `ActiveRecord::StatementInvalid`. Structured but only two classes — no separate not-null or check violation types.

### Laravel

Eloquent raises `Illuminate\Database\UniqueConstraintViolationException` (since Laravel 10). Other violations surface as raw `QueryException`. Laravel is gradually adding structured exceptions but isn't complete yet.

## Implementation

The conversion would happen at the database backend level — wherever psycopg exceptions are caught and re-raised as Plain exceptions. Check the `pgcode` on the psycopg error and raise the appropriate subclass. Since they're all subclasses of `IntegrityError`, existing `except IntegrityError` handlers continue to work.
