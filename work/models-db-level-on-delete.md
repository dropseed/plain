---
labels:
- plain-postgres
related:
- remove-signals
- models-foreignkey-deferred-loading
---

# DB-Level ON DELETE for Foreign Keys

## Problem

Plain's `on_delete` behavior is entirely application-level. When you delete a model instance, Python's `Collector` class:

1. Walks the entire relationship graph recursively
2. Loads every related object into memory
3. Executes separate DELETE/UPDATE statements per batch

This is slow, memory-intensive, and unnecessary for the common cases (CASCADE, SET_NULL). PostgreSQL handles these natively via `ON DELETE` clauses — no round trips, no objects loaded into Python.

## Current State

- **Plain generates no `ON DELETE` SQL** — FK constraints in `schema.py` have no on_delete clause (lines 380-387)
- **All FKs are `DEFERRABLE INITIALLY DEFERRED`** — constraint checks happen at transaction commit
- **No delete signals exist** — `pre_delete`/`post_delete` are already gone (the main reason Django keeps the Collector)
- **Production usage**: Plain's own packages use only `CASCADE` (7 FKs) and `SET_NULL` (2 FKs). `PROTECT`/`RESTRICT`/`SET_DEFAULT`/`DO_NOTHING` only appear in tests.

## Proposal: Make DB-level the default (and possibly only) option

Since Plain has no delete signals, the primary reason for application-level deletion handling is gone. The question is whether to:

### Option A: DB-level only (drop the Collector for on_delete)

Map `on_delete` directly to SQL `ON DELETE` clauses:

| Plain                    | SQL                                         |
| ------------------------ | ------------------------------------------- |
| `CASCADE`                | `ON DELETE CASCADE`                         |
| `SET_NULL`               | `ON DELETE SET NULL`                        |
| `SET_DEFAULT`            | `ON DELETE SET DEFAULT`                     |
| `RESTRICT`               | `ON DELETE RESTRICT`                        |
| `DO_NOTHING` / no action | No clause (Postgres default is `NO ACTION`) |

`Model.delete()` and `QuerySet.delete()` become simple `DELETE FROM` statements — no Collector, no graph walking.

### Option B: DB-level default with Python escape hatch

Same as A, but keep a simplified Collector for edge cases like `PROTECT` (nice Python error messages) or `SET(callable)`.

## How Other Frameworks Handle This

### Ecto (Phoenix) — DB-level only

Ecto pushes all FK constraints to the database. Options in migrations: `:delete_all` (CASCADE), `:nilify_all` (SET NULL), `:restrict` (RESTRICT), `:nothing` (NO ACTION). There is no application-level cascade mechanism at all. If you want side effects on delete, you explicitly load and delete records in application code.

### Rails — Application-level default, DB-level available

Rails defaults to **no ON DELETE clause** (NO ACTION). Application-level cascading via `dependent: :destroy` (loads each child, fires callbacks, deletes) or `dependent: :delete_all` (bulk DELETE, no callbacks). DB-level `on_delete: :cascade` is available in migrations but opt-in. Many production apps use both: DB-level CASCADE as a safety net, application-level callbacks for business logic.

### Laravel — DB-level is the norm

Laravel's FK migrations use explicit `->onDelete('cascade')` / `->onDelete('set null')` that map directly to SQL. Application-level cascading is not built in — you'd manually handle it in model events. DB-level is the standard community recommendation.

### Django — Application-level default, DB-level added in 6.1

Django defaults to application-level via the Collector (for signal support). Django 6.1 adds `DB_CASCADE`, `DB_SET_NULL`, `DB_SET_DEFAULT` as opt-in alternatives. Django can't change the default because of backwards compat with signals.

### Summary

| Framework   | Default   | App-level cascade? | DB-level cascade?  |
| ----------- | --------- | ------------------ | ------------------ |
| **Ecto**    | DB-level  | No                 | Yes (only option)  |
| **Laravel** | DB-level  | No (manual)        | Yes (standard)     |
| **Rails**   | App-level | Yes (dependent)    | Yes (opt-in)       |
| **Django**  | App-level | Yes (Collector)    | Yes (opt-in, 6.1+) |

Plain is in a unique position: no delete signals (unlike Django/Rails), Postgres-only (unlike Django's multi-DB), and no backwards compat constraint. The Ecto/Laravel approach — DB-level as the only/primary path — is the natural fit.

## What you gain

- **Performance**: No objects loaded into memory for cascading deletes. A `DELETE FROM parent WHERE id = 1` just works — Postgres handles the cascade internally.
- **Simplicity**: No `Collector` class (currently 475 lines). `Model.delete()` becomes a simple DELETE query. `QuerySet.delete()` becomes `_raw_delete()`.
- **Correctness**: DB-level constraints are enforced even if you bypass the ORM (raw SQL, migrations, external tools).
- **Memory**: Deleting a parent with 100K children doesn't load 100K objects into Python.

## What you lose

- **`PROTECT` with nice errors**: DB-level `RESTRICT` raises a raw `IntegrityError`, not a descriptive `ProtectedError("Cannot delete User because it is referenced by Post.author")`. Could be recovered with error parsing or a pre-delete check query.
- **`SET(callable)`**: DB-level can only set to NULL, DEFAULT, or RESTRICT. Dynamic values (e.g., `SET(get_sentinel_user)`) require either a Postgres trigger or pre-delete application logic.
- **Delete return value**: Currently `Model.delete()` returns `(count, {model_label: count})` showing the full cascade breakdown. With DB-level deletes, you'd only get the direct delete count (Postgres doesn't report cascaded row counts). Could query `pg_stat_*` or just return the direct count.
- **Admin "confirm delete" preview**: Django's admin shows "these objects will be deleted" by running the Collector without committing. Plain's admin would need a different approach (e.g., query the relationship graph without actually deleting).

## Implementation sketch

### Schema changes

Add `ON DELETE` to FK SQL templates in `schema.py`:

```python
sql_create_fk = (
    "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) "
    "REFERENCES %(to_table)s (%(to_column)s)%(on_delete)s%(deferrable)s"
)
```

Map `on_delete` values to SQL in `_create_fk_sql`:

```python
ON_DELETE_SQL = {
    CASCADE: " ON DELETE CASCADE",
    SET_NULL: " ON DELETE SET NULL",
    SET_DEFAULT: " ON DELETE SET DEFAULT",
    RESTRICT: " ON DELETE RESTRICT",
    DO_NOTHING: "",  # Postgres default (NO ACTION)
}
```

### Simplify Model.delete() / QuerySet.delete()

```python
# Model.delete() becomes:
def delete(self):
    count = type(self).query.filter(id=self.id)._raw_delete()
    self.id = None
    return count

# QuerySet.delete() becomes:
def delete(self):
    return self._raw_delete()
```

### Migration

Every existing FK constraint needs to be recreated with the ON DELETE clause. This is a one-time migration per model. For Plain's own packages, that's ~9 foreign keys.

## Open questions

1. **Should PROTECT survive?** It's useful for preventing accidental deletion of referenced data. Options: (a) keep as a pre-delete check in Python, (b) use `RESTRICT` and catch/wrap the IntegrityError, (c) drop it.
2. **What about the cascade count return value?** Is `(count, {label: count})` actually used by anyone, or can we simplify to just returning the count of directly deleted rows?
3. **Admin delete preview** — how should this work without the Collector? Query FK metadata to show what would cascade?
4. **SET(callable)** — is this used in practice? If so, Postgres triggers or pre-delete logic?
