---
paths:
  - "**/models.py"
  - "**/models/**"
---

# Database & Models

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

Only write migrations by hand for custom data migrations. Run `uv run plain docs models --section migrations` for full details.

## Querying

Use `Model.query` not `Model.objects` (e.g., `User.query.filter(is_active=True)`).

- Use `select_related()` for FK access in loops, `prefetch_related()` for reverse/M2N
- Use `.annotate(Count(...))` instead of calling `.count()` per row
- Fetch all data in the view — templates should never trigger queries
- Use `.exists()` not `.count() > 0`, `.count()` not `len(qs)`
- Use `bulk_create`/`bulk_update` for batch ops, `.update()`/`.delete()` for mass ops
- Use `.values_list()` when you only need specific columns

Run `uv run plain docs models --section querying` for full patterns with code examples.

## Schema Design

- Index fields used in `.filter()` and `.order_by()`
- Use `UniqueConstraint` in constraints, not `unique=True` on fields
- Choose `on_delete` deliberately: CASCADE for children, PROTECT for referenced data
- No `allow_null` on string fields — use `default=""`

Run `uv run plain docs models --section constraints` for full patterns with code examples.
