---
paths:
  - "**/*.py"
---

# Database & Models

## Field Imports

Import fields via `from plain.postgres import types`. Don't add primitive
annotations — the field stubs return typed descriptors that resolve to the
right value type on instance access:

```python
from plain.postgres import types

name = types.TextField(max_length=100)
car = types.ForeignKeyField(Car, on_delete=postgres.CASCADE)
```

For string forward references (`"self"`, `"OtherModel"`), the type checker
can't infer the target type from the string — annotate explicitly so
instance access keeps its type:

```python
parent: TreeNode | None = types.ForeignKeyField("self", on_delete=postgres.CASCADE, allow_null=True)
```

For `JSONField` and `EncryptedJSONField`, the stub returns `Any` (the
runtime class isn't generic over its value shape), so annotate explicitly
to preserve typing:

```python
parameters: dict[str, Any] | None = types.JSONField(required=False, allow_null=True)
config: dict | None = types.EncryptedJSONField(required=False, allow_null=True)
```

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
