# DB-level defaults via `default` param

## Problem

The `default` field parameter currently only accepts Python values and callables. When a migration adds a non-nullable field with a callable default (like `default=uuid.uuid4`) to a table with existing rows, the callable is evaluated **once** in Python and used as a static SQL `DEFAULT` for all existing rows. Every row gets the same UUID. This is a data integrity bug for any field where uniqueness matters.

Django solved this in 5.0 by adding a separate `db_default` parameter. But having both `default` and `db_default` creates confusion — users reach for the familiar `default=timezone.now` and hit the migration bug. Two params means explaining precedence rules, sentinel objects for unsaved instances, and when to use which.

## Solution

Extend the existing `default` parameter to accept Postgres SQL expressions alongside static values. No new parameter.

```python
# SQL expression → DB DEFAULT gen_random_uuid()
uuid = UUIDField(default=GenRandomUUID())

# SQL expression → DB DEFAULT now()
created_at = DateTimeField(default=Now())

# Static value → DB DEFAULT 'pending' (works today, also becomes a DB default)
status = TextField(default="pending")

# Python callable → still works for now (existing behavior, deprecate later)
token = CharField(default=get_random_string)
```

The field/schema-editor checks `isinstance(default, DBExpression)` to decide whether to emit a SQL `DEFAULT` clause or evaluate in Python.

### What this replaces

- **No `db_default` parameter** — one param, not two. No precedence confusion.
- **No `CreatedAtField` / `UpdatedAtField`** — just `DateTimeField(default=Now())`. Dedicated field types for the same column type add taxonomy without value. The column is `timestamptz` either way.
- **No `UUIDField(version=4)`** — just `UUIDField(default=GenRandomUUID())`. Explicit about what SQL function runs.
- **No `auto_now` / `auto_now_add`** — `default=Now()` replaces `auto_now_add`. `auto_now` (set on every update) is a separate concern — see "updated_at" section below.

### Why not separate `db_default`?

Plain is Postgres-only. The reason Django needs two params is backend compatibility — SQLite doesn't support expression defaults. Plain doesn't have that constraint. A single `default` that's smart about SQL expressions is simpler and eliminates the "which one do I use?" question.

## How DB expression defaults work

### Column DDL

The schema editor emits `DEFAULT <sql>` on the column:

```sql
ALTER TABLE drains ADD COLUMN uuid uuid DEFAULT gen_random_uuid() NOT NULL;
```

The DEFAULT persists on the column (unlike Python callable defaults, which are added temporarily then dropped). This means:

- Existing rows get per-row unique values during migration (Postgres evaluates the function per row)
- Future rows inserted via raw SQL, other services, or pg_dump/restore get correct defaults
- The callable-evaluated-once migration bug is structurally impossible

### INSERT behavior

When the ORM inserts a row:

- If no value was explicitly set → omit the column from INSERT, let Postgres use DEFAULT
- If a value was explicitly set → include it in INSERT (manual override works)

Fields with DB expression defaults set `db_returning = True` so the ORM gets the actual value back via `RETURNING` after INSERT.

### Unsaved instances

Before save, accessing a field with a DB expression default returns a sentinel (like Django's `DatabaseDefault`). The real value is only known after the DB evaluates it. For most cases (uuid, created_at) you don't need the value before save. For cases where you do, set it explicitly in Python.

### Migrations and convergence

In the current migration system: the schema editor uses the SQL expression directly in `ALTER TABLE ADD COLUMN ... DEFAULT <expr>`. The callable-evaluated-once problem goes away.

In the convergence future: `default=Now()` is desired state on the column. Convergence applies `SET DEFAULT now()` and manages backfills using the DB function per-row. Migrations never touch defaults at all.

## `updated_at` — the remaining special case

`default=Now()` handles INSERT. But "set to now() on every UPDATE" has no SQL `DEFAULT` equivalent in Postgres — it requires either:

1. **Application-level `pre_save`** — the current approach, keeps working
2. **A Postgres trigger** — convergence could manage this in the future:
    ```python
    updated_at = DateTimeField(default=Now(), on_update=Now())
    ```
    Convergence creates/maintains a `BEFORE UPDATE` trigger that sets the column to `now()`. This is the cleanest long-term solution but requires convergence infrastructure.

For now, `auto_now=True` or explicit `pre_save` logic handles this. The trigger approach is worth noting as future potential.

## Phased implementation

### Phase 1: Accept DB expressions in `default` (independent of migration rethink)

- Add base class for DB expressions (or reuse existing `Expression` classes)
- Provide `Now()` and `GenRandomUUID()` builtins
- Schema editor checks `isinstance(default, DBExpression)` → emits SQL DEFAULT
- Fields with DB expression defaults get `db_returning = True`
- INSERT compiler omits columns with DB expression defaults when no value is set
- Python callable defaults continue working (no breaking change)

### Phase 2: Deprecate Python callable defaults

- Warn on `default=timezone.now` ("use default=Now()")
- Warn on `default=uuid.uuid4` ("use default=GenRandomUUID()")
- Custom callables (`default=get_random_string`) → warn, suggest setting in model code

### Phase 3: Block callable defaults (with convergence)

- `default` accepts only static values and DB expressions
- Callable defaults error with a clear message
- Token/slug generation moves to model `create()` or form logic
- Aligns with thin-fields philosophy: fields declare column state, not behavior

## UUIDv7

Postgres 18 adds `uuidv7()`. When Plain's minimum Postgres version includes it:

```python
uuid = UUIDField(default=UUIDv7())  # → DB DEFAULT uuidv7()
```

Same field, same column type (`uuid`), different expression. No new field types needed. The migration from v4 to v7 is just changing the default expression — convergence applies `ALTER COLUMN SET DEFAULT uuidv7()`.

UUIDv7 is time-ordered, dramatically better for B-tree index performance (sequential inserts vs random page splits). It should become the recommended default once available.

## Guiding principles

- **Same column type = same field type.** `uuid` is always `UUIDField`, `timestamptz` is always `DateTimeField`. Generation strategy is a parameter, not a type.
- **Fields describe columns, not behavior.** Thin fields: type, constraints, defaults. Auto-generation logic moves to DB expressions and convergence, not field subclasses.
- **One `default`, not two.** A single parameter that handles both static values and DB expressions. No `db_default` vs `default` confusion.
- **DB defaults over Python defaults.** Postgres-first means letting Postgres handle what it's good at. DB defaults work for migrations, raw SQL, and the ORM. Python defaults only work for the ORM.

## Industry context

- **Django 5.0** added `db_default` as a separate parameter — needed for multi-backend compat
- **Rails** uses DB defaults for UUID PKs (`gen_random_uuid()`) but app-level for timestamps
- **Prisma/Drizzle** use DB defaults for everything (`@default(now())`, `@default(uuid())`)
- **SQLAlchemy** has `default` vs `server_default` — same two-param confusion as Django

Plain's single-`default` approach is simpler than all of these because it can assume Postgres.
