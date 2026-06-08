---
paths:
  - "**/*.py"
---

# Database & Models

## Field Imports & Annotations

Import fields via `from plain.postgres import types`, and annotate each field
with `Field[T]` (the value type). The annotation is what gives the model a
type-checked constructor — `Model(field=value)` then flags wrong value types,
unknown field names, and missing required fields:

```python
from datetime import datetime

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class Article(postgres.Model):
    title: Field[str] = types.TextField(max_length=100)
    views: Field[int] = types.IntegerField(default=0)
    author: Field[User] = types.ForeignKeyField(User, on_delete=postgres.CASCADE)
    published_at: Field[datetime | None] = types.DateTimeField(allow_null=True, default=None)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
```

- **Value type**: `Field[str]`, `Field[int]`, `Field[datetime]`; for an FK to a
  model class, `Field[RelatedModel]`.
- **Nullable** (`allow_null=True`) → `Field[T | None]` **and** add `default=None`
  so the field is optional in the constructor (a stock type checker only reads
  optionality from a call-site `default=`).
- **DB-owned** fields are still annotated but auto-excluded from the
  constructor: the `id`, `create_now`/`update_now` datetimes, `generate=True`,
  and `RandomStringField`.
- **String forward-ref FKs** (`"self"`, `"OtherModel"`) keep a _value-type_
  annotation — the checker can't resolve the string to a model:
  `parent: Foo | None = types.ForeignKeyField("self", on_delete=postgres.CASCADE, allow_null=True)`.
- **JSON**: `Field[dict]` / `Field[dict[str, Any]]`.
- **Custom querysets**: declare `query: ClassVar[MyQuerySet] = MyQuerySet()`
  (`ClassVar` so it isn't treated as a field). Default-queryset models declare
  nothing — `Model.query` is typed automatically.

Do NOT import field classes directly from `plain.postgres` or `plain.postgres.fields`.

## Schema Changes

When creating new models or modifying existing model fields/relationships, always enter plan mode first. Database schema is hard to change after the fact, so get the design right before writing code.

In your plan, present:

- Proposed schema as a table (model, field, type, constraints)
- Relationship cardinality (1:1, 1:N, M:N)
- Key decisions: nullable vs default, indexing, cascade behavior
- Whether the data could live on an existing model instead of a new one

Get approval before writing any model code or generating migrations.

## Migrations vs Convergence

`uv run plain postgres sync` runs three steps: create migrations → apply migrations → converge schema.

- **Migrations** handle tables and columns (CreateModel, AddField, AlterField, etc.)
- **Convergence** handles indexes, constraints, FK constraints, and storage parameters — declared on the model but NOT serialized into migration files. (FK _columns_ like `team_id bigint` are created by migrations; the actual `FOREIGN KEY` constraint is added by convergence.)

This means: when you add an `Index` or `UniqueConstraint` to a model, no migration is generated. The converge step reads the live model class and syncs the database directly. Don't worry about serializing constraint expressions (like `Lower()`) for migrations — they never go there.

For custom data migrations, use `uv run plain migrations create --empty --name <name>` to scaffold the file.

Run `uv run plain docs postgres` for full workflow details.

## Querying

Use `Model.query` to build querysets (e.g., `User.query.filter(is_active=True)`).

- Use `select_related()` for FK access in loops, `prefetch_related()` for reverse/M2N
- A foreign key returns a partial related object: `obj.author` and `obj.author.id` are query-free; other fields load on first access. There is no `obj.author_id` — use `obj.author.id`
- Use `.annotate(Count(...))` instead of calling `.count()` per row
- Fetch all data in the view — templates should never trigger queries
- Use `.exists()` not `.count() > 0`, `.count()` not `len(qs)`
- Use `bulk_create`/`bulk_update` for batch ops, `.update()`/`.delete()` for mass ops
- Use `.values_list()` when you only need specific columns
- Wrap multi-step writes in `transaction.atomic()`
- Instance writes are `obj.create()` (always INSERT) and `obj.update()` (always UPDATE; `update(fields=[...])` limits the columns) — there is no `save()`, `force_insert`, or `force_update`. Constructing an instance then `create()`-ing it inserts; a hand-set `id` that collides raises `IntegrityError`.
- `create()`/`update()` raise `ValidationError` (not raw `psycopg.IntegrityError`) on a declared unique/check constraint violation, even a raced one — the DB enforces it, so inside an open `transaction.atomic()` the violation aborts the transaction (wrap the write in its own `atomic()` to catch and keep using the transaction). Set-based writes (`QuerySet.update()`/`bulk_create()`) raise raw `psycopg.IntegrityError`. Retrying on conflict? `except (psycopg.IntegrityError, ValidationError)`, or `bulk_create(..., update_conflicts=True)`
- Always paginate list queries — unbounded querysets get slower as data grows

Run `uv run plain docs postgres` for full patterns with code examples.

## Schema Design

- Always index FK columns — Postgres doesn't auto-create these. Use an `Index`, or a constraint with the FK as the first field.
- Index fields used in `.filter()` and `.order_by()`
- Indexes: `{table}_{column(s)}_idx`
- Constraints: `{table}_{column(s)}_{type}` (e.g., `_unique`, `_check`)
- Choose `on_delete` deliberately: CASCADE for owned children, RESTRICT for referenced data, SET_NULL for optional references
- No `allow_null` on string fields — use `default=""`

Run `uv run plain docs postgres` for full patterns with code examples.

## Database Doctor

Use the `/plain-postgres-doctor` skill to check overall database health — migration sync, schema correctness, and operational health.

Run `uv run plain docs postgres` for check details, thresholds, and production usage.

## Differences from Django

- Use `Model.query` not `Model.objects`
- Import fields from `plain.postgres.types` not `plain.postgres.fields` — and don't import field classes directly from `plain.postgres`
- Use `model_options = postgres.Options(...)` not `class Meta`
- Never format raw SQL strings — always use parameterized queries
- Migrations are forward-only — no reverse migrations. `RunPython` takes a single callable (no `reverse_code` or `noop`). The callable signature is `fn(models, schema_editor)`, not `fn(apps, schema_editor)`
