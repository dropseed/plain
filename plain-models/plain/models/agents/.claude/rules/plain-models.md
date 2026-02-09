# Database & Models

## Schema Changes

When creating new models or modifying existing model fields/relationships, always enter plan mode first. Database schema is hard to change after the fact, so get the design right before writing code.

In your plan, present:

- Proposed schema as a table (model, field, type, constraints)
- Relationship cardinality (1:1, 1:N, M:N)
- Key decisions: nullable vs default, indexing, cascade behavior
- Whether the data could live on an existing model instead of a new one

Get approval before writing any model code or generating migrations.

## Creating Migrations

```
uv run plain makemigrations
```

Only write migrations by hand if they are custom data migrations.

## Running Migrations

```
uv run plain migrate --backup
```

The `--backup` flag creates a database backup before applying migrations.

Run `uv run plain docs models --source` for detailed model and migration documentation.

## Querying

Use `Model.query` to build querysets:

- `User.query.all()`
- `User.query.filter(is_active=True)`
- `User.query.get(pk=1)`
- `User.query.exclude(role="admin")`

Run `uv run plain docs models --api` for the full query API.
