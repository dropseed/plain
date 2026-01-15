---
name: plain-models
description: Manages database migrations and model changes. Use when creating migrations, running migrations, or modifying models.
user-invocable: false
---

# Database Migrations

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

## Getting Package Docs

Run `uv run plain docs models --source` for detailed model and migration documentation.
