---
paths:
  - "**/*.py"
---

# Database & Models

## Field Imports

Import fields via `from plain.postgres import types` and annotate with Python types:

```python
from plain.postgres import types

name: str = types.CharField(max_length=100)
car: Car = types.ForeignKeyField("Car", on_delete=postgres.CASCADE)
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

## Migrations

- `uv run plain makemigrations` — create migrations (`--dry-run` to preview, `--check` for CI)
- `uv run plain migrate --backup` — apply migrations
- `uv run plain migrations list` — view status (not `migrate --list`)
- Before committing, consolidate multiple uncommitted migrations into one:
  delete the intermediate files, run `migrations prune --yes` to clean stale DB records,
  run `makemigrations` fresh, then `migrate --fake` to mark it applied
- Use `migrations squash` only for already-committed/deployed migrations — never for dev cleanup
- Only write migrations by hand for custom data migrations

Run `uv run plain docs postgres --section migrations` for full workflow details.

## Querying

Use `Model.query` to build querysets (e.g., `User.query.filter(is_active=True)`).

- Use `select_related()` for FK access in loops, `prefetch_related()` for reverse/M2N
- Use `.annotate(Count(...))` instead of calling `.count()` per row
- Fetch all data in the view — templates should never trigger queries
- Use `.exists()` not `.count() > 0`, `.count()` not `len(qs)`
- Use `bulk_create`/`bulk_update` for batch ops, `.update()`/`.delete()` for mass ops
- Use `.values_list()` when you only need specific columns
- Wrap multi-step writes in `transaction.atomic()`
- Always paginate list queries — unbounded querysets get slower as data grows

Run `uv run plain docs postgres --section querying` for full patterns with code examples.

## Schema Design

- Index fields used in `.filter()` and `.order_by()`
- `Index` requires a `name` argument — use `{table}_{column(s)}_idx` (e.g., `plainjobs_jobrequest_priority_idx`, `plainobserver_log_trace_id_timestamp_idx`)
- Use `UniqueConstraint` in constraints, not `unique=True` on fields
- Choose `on_delete` deliberately: CASCADE for children, PROTECT for referenced data
- No `allow_null` on string fields — use `default=""`

Run `uv run plain docs postgres --section constraints` for full patterns with code examples.

## Database Doctor

Use the `/plain-postgres-doctor` skill to check overall database health — migration sync, schema correctness, and operational health.

Run `uv run plain docs postgres --section diagnostics` for check details, thresholds, and production usage.

## Differences from Django

- Use `Model.query` not `Model.objects`
- Import fields from `plain.postgres.types` not `plain.postgres.fields` — and don't import field classes directly from `plain.postgres`
- Use `model_options = postgres.Options(...)` not `class Meta`
- Fields don't accept `unique=True` — use `UniqueConstraint` in constraints
- Never format raw SQL strings — always use parameterized queries
- Migrations are forward-only — no reverse migrations. `RunPython` takes a single callable (no `reverse_code` or `noop`). The callable signature is `fn(models, schema_editor)`, not `fn(apps, schema_editor)`
