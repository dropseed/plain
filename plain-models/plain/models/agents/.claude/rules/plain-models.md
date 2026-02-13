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

### Creating Migrations

```
uv run plain makemigrations
```

Key flags:

- `--dry-run` — Show what migrations would be created (with operations and SQL) without writing files
- `--check` — Exit non-zero if migrations are needed (for CI)
- `--empty <package>` — Create an empty migration for custom data migrations
- `--name <name>` — Set the migration filename
- `-v 3` — Show full migration file contents

Only write migrations by hand if they are custom data migrations.

### Running Migrations

```
uv run plain migrate --backup
```

Key flags:

- `--backup` / `--no-backup` — Create a database backup before applying (default: on in DEBUG)
- `--plan` — Show what migrations would run without applying them
- `--check` — Exit non-zero if unapplied migrations exist (for CI)
- `--fake` — Mark migrations as applied without running them

### Viewing Migration Status

```
uv run plain migrations list
```

`migrate` has no `--list` or `--status` flag. Use `plain migrations list`.

- `--format plan` — Show in dependency order instead of grouped by package

### Other Migration Commands

- `uv run plain migrations squash <package> <migration>` — Squash migrations into one
- `uv run plain migrations prune` — Remove stale migration records

Run `uv run plain docs models --source` for detailed model and migration documentation.

## Querying

Use `Model.query` to build querysets:

- `User.query.all()`
- `User.query.filter(is_active=True)`
- `User.query.get(pk=1)`
- `User.query.exclude(role="admin")`

Run `uv run plain docs models --api` for the full query API.
